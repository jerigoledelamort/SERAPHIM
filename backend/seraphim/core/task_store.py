# CORE task persistence (S17). A state change, its event row and its checkpoint
# are written in ONE transaction, guarded by a revision check: a stale writer
# gets TASK_REVISION_CONFLICT and nothing is written.
#
# The plan definition (goal, mode, step ids, dependencies, criteria) is written
# once at creation. Only state fields change afterwards.

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.contracts.timestamps import now_utc, validate_timestamp
from seraphim.core.task_machine import transition
from seraphim.core.task_model import (
    COMPONENT,
    CheckOutcome,
    PlanStep,
    StepStatus,
    Task,
    TaskMode,
    TaskResult,
    TaskStatus,
    VerificationReport,
    check_invariants,
)
from seraphim.storage.db import Database

T = TaskStatus

# A task flagged for review may only be closed by an operator, never advanced.
OPERATOR_END_STATUSES = frozenset({T.CANCELLED, T.FAILED, T.BLOCKED})

CALL_STARTED = "STARTED"
CALL_COMPLETED = "COMPLETED"
CALL_FAILED = "FAILED"
CALL_UNKNOWN = "UNKNOWN"


def _err(code: str, message: str, *, task_id: str = "", user_action: bool = False) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        task_id=task_id,
        user_action_required=user_action,
    )


@dataclass(frozen=True)
class TaskRecord:
    """A task as stored, with the revision it was read at."""

    task: Task
    revision: int
    session_id: str
    review_required: bool
    review_reason: str


def _report_obj(report: VerificationReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "verifier_id": report.verifier_id,
        "checks": [
            {"name": c.name, "passed": c.passed, "evidence_ref": c.evidence_ref}
            for c in report.checks
        ],
    }


def _report_from_obj(data: dict[str, Any] | None) -> VerificationReport | None:
    if data is None:
        return None
    return VerificationReport(
        data["verifier_id"],
        tuple(CheckOutcome(c["name"], c["passed"], c["evidence_ref"]) for c in data["checks"]),
    )


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _result_to_json(result: TaskResult | None) -> str:
    if result is None:
        return ""
    return _dumps(
        {
            "outcome": result.outcome.value,
            "reason": result.reason,
            "error_code": result.error_code,
            "verification": _report_obj(result.verification),
        }
    )


def _result_from_json(raw: str) -> TaskResult | None:
    if not raw:
        return None
    data = json.loads(raw)
    return TaskResult(
        outcome=T(data["outcome"]),
        reason=data["reason"],
        error_code=data["error_code"],
        verification=_report_from_obj(data["verification"]),
    )


PLAN_SCHEMA_VERSION = 1


def _plan_to_json(constraints: tuple[str, ...], steps: tuple[PlanStep, ...]) -> str:
    return _dumps(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "constraints": list(constraints),
            "steps": [
                {
                    "id": s.id,
                    "title": s.title,
                    "verification": list(s.verification),
                    "depends_on": list(s.depends_on),
                    "expected_outputs": list(s.expected_outputs),
                    "max_attempts": s.max_attempts,
                    "requires_approval": s.requires_approval,
                    "risk_hint": s.risk_hint,
                }
                for s in steps
            ],
        }
    )


def _plan_from_json(raw: str) -> tuple[tuple[str, ...], tuple[PlanStep, ...]]:
    data = json.loads(raw)
    if data.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise _err(ErrorCode.TASK_INVALID, "Stored plan has an unsupported schema version.")
    steps = tuple(
        PlanStep(
            id=d["id"],
            title=d["title"],
            verification=tuple(d["verification"]),
            depends_on=tuple(d["depends_on"]),
            expected_outputs=tuple(d["expected_outputs"]),
            max_attempts=d["max_attempts"],
            requires_approval=d["requires_approval"],
            risk_hint=d["risk_hint"],
        )
        for d in data["steps"]
    )
    return tuple(data["constraints"]), steps


def _checkpoint_summary(task: Task) -> str:
    return _dumps(
        {
            "status": task.status.value,
            "pending_verification": task.pending_verification,
            "pending_approval_step": task.pending_approval_step,
            "steps": {s.id: s.status.value for s in task.steps},
        }
    )


def _write_event(
    conn: sqlite3.Connection,
    db: Database,
    *,
    event_type: str,
    task_id: str,
    session_id: str,
    payload: dict[str, Any],
    at: str,
) -> None:
    db.insert_row(
        "events",
        {
            "id": generate_id("event"),
            "timestamp": at,
            "type": event_type,
            "component": COMPONENT,
            "task_id": task_id,
            "session_id": session_id,
            "payload_json": _dumps(payload),
        },
        connection=conn,
    )


class TaskRepository:
    """Transactional access to tasks, steps, checkpoints and events."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(self, task: Task, *, session_id: str = "") -> TaskRecord:
        validate_timestamp(task.updated_at)
        check_invariants(task)
        if task.status is not TaskStatus.DRAFT or task.result is not None:
            raise _err(ErrorCode.TASK_INVALID, "Only a new DRAFT task can be inserted.", task_id=task.id)
        with self._db.transaction() as conn:
            self._db.insert_row(
                "tasks",
                {
                    "id": task.id,
                    "session_id": session_id or None,
                    "goal": task.goal,
                    "mode": task.mode.value,
                    "status": task.status.value,
                    "plan_json": _plan_to_json(task.constraints, task.steps),
                    "created_at": task.updated_at,
                    "updated_at": task.updated_at,
                    "revision": 0,
                    "pending_verification": task.pending_verification,
                    "pending_approval_step": task.pending_approval_step,
                    "approved_step_id": task.approved_step_id,
                    "result_json": _result_to_json(task.result),
                },
                connection=conn,
            )
            for step in task.steps:
                conn.execute(
                    "INSERT INTO task_steps (task_id, step_id, status, attempts, report_json,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        task.id,
                        step.id,
                        step.status.value,
                        step.attempts,
                        _dumps(_report_obj(step.report)) if step.report else "",
                        task.updated_at,
                    ),
                )
            conn.execute(
                "INSERT INTO checkpoints (id, task_id, revision, created_at, summary_json)"
                " VALUES (?, ?, 0, ?, ?)",
                (generate_id("checkpoint"), task.id, task.updated_at, _checkpoint_summary(task)),
            )
            _write_event(
                conn,
                self._db,
                event_type="TaskCreated",
                task_id=task.id,
                session_id=session_id,
                payload={"status": task.status.value},
                at=task.updated_at,
            )
        return self.load(task.id)

    def load(self, task_id: str) -> TaskRecord:
        row = self._db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise _err(ErrorCode.TASK_NOT_FOUND, "Task not found.", task_id=task_id)
        step_rows = {
            r["step_id"]: r
            for r in self._db.query(
                "SELECT step_id, status, attempts, report_json FROM task_steps WHERE task_id = ?",
                (task_id,),
            )
        }
        constraints, plan_steps = _plan_from_json(row["plan_json"])
        steps = tuple(
            replace(
                s,
                status=StepStatus(step_rows[s.id]["status"]),
                attempts=step_rows[s.id]["attempts"],
                report=_report_from_obj(
                    json.loads(step_rows[s.id]["report_json"]) if step_rows[s.id]["report_json"] else None
                ),
            )
            for s in plan_steps
        )
        task = Task(
            id=row["id"],
            goal=row["goal"],
            mode=TaskMode(row["mode"]),
            steps=steps,
            updated_at=row["updated_at"],
            constraints=constraints,
            status=T(row["status"]),
            result=_result_from_json(row["result_json"]),
            pending_verification=row["pending_verification"],
            pending_approval_step=row["pending_approval_step"],
            approved_step_id=row["approved_step_id"],
        )
        return TaskRecord(
            task=task,
            revision=int(row["revision"]),
            session_id=row["session_id"] or "",
            review_required=bool(row["review_required"]),
            review_reason=row["review_reason"],
        )

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        if status is None:
            rows = self._db.query("SELECT id FROM tasks ORDER BY created_at, id")
        else:
            rows = self._db.query(
                "SELECT id FROM tasks WHERE status = ? ORDER BY created_at, id", (status.value,)
            )
        return [self.load(r["id"]) for r in rows]

    def save(self, record: TaskRecord, event: object, *, event_type: str, at: str) -> TaskRecord:
        validate_timestamp(at)
        new_task = transition(record.task, event, at=at)
        with self._db.transaction() as conn:
            current = conn.execute(
                "SELECT revision, review_required, session_id FROM tasks WHERE id = ?",
                (new_task.id,),
            ).fetchone()
            if current is None:
                raise _err(ErrorCode.TASK_NOT_FOUND, "Task not found.", task_id=new_task.id)
            if int(current["revision"]) != record.revision:
                raise _err(
                    ErrorCode.TASK_REVISION_CONFLICT,
                    "Task was changed by another writer; reload and retry.",
                    task_id=new_task.id,
                )
            if current["review_required"] and new_task.status not in OPERATOR_END_STATUSES:
                raise _err(
                    ErrorCode.TASK_REVIEW_REQUIRED,
                    "Task requires review before it can change state.",
                    task_id=new_task.id,
                    user_action=True,
                )
            revision = record.revision + 1
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, revision = ?,"
                " pending_verification = ?, pending_approval_step = ?, approved_step_id = ?,"
                " result_json = ? WHERE id = ? AND revision = ?",
                (
                    new_task.status.value,
                    at,
                    revision,
                    new_task.pending_verification,
                    new_task.pending_approval_step,
                    new_task.approved_step_id,
                    _result_to_json(new_task.result),
                    new_task.id,
                    record.revision,
                ),
            )
            for step in new_task.steps:
                conn.execute(
                    "UPDATE task_steps SET status = ?, attempts = ?, report_json = ?, updated_at = ?"
                    " WHERE task_id = ? AND step_id = ?",
                    (
                        step.status.value,
                        step.attempts,
                        _dumps(_report_obj(step.report)) if step.report else "",
                        at,
                        new_task.id,
                        step.id,
                    ),
                )
            conn.execute(
                "INSERT INTO checkpoints (id, task_id, revision, created_at, summary_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    generate_id("checkpoint"),
                    new_task.id,
                    revision,
                    at,
                    _checkpoint_summary(new_task),
                ),
            )
            _write_event(
                conn,
                self._db,
                event_type=event_type,
                task_id=new_task.id,
                session_id=current["session_id"] or "",
                payload={"from": record.task.status.value, "to": new_task.status.value},
                at=at,
            )
        return self.load(new_task.id)

    def set_review(self, task_id: str, *, required: bool, reason: str, at: str) -> TaskRecord:
        validate_timestamp(at)
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET review_required = ?, review_reason = ?, updated_at = ?,"
                " revision = revision + 1 WHERE id = ?",
                (1 if required else 0, reason, at, task_id),
            )
            if cursor.rowcount != 1:
                raise _err(ErrorCode.TASK_NOT_FOUND, "Task not found.", task_id=task_id)
            row = conn.execute("SELECT session_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            _write_event(
                conn,
                self._db,
                event_type="ReviewRequired" if required else "ReviewCleared",
                task_id=task_id,
                session_id=row["session_id"] or "",
                payload={"reason": reason},
                at=at,
            )
        return self.load(task_id)


class ToolCallLedger:
    """Records each external operation before it runs.

    A call still STARTED after a process stop has an unknown outcome. Recovery
    marks it UNKNOWN and flags the task for review; the call is never re-issued
    by the runtime. The idempotency key is UNIQUE, so one key cannot be recorded
    twice.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def begin(self, task_id: str, step_id: str, operation: str, idempotency_key: str) -> str:
        call_id = generate_id("call")
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT status, review_required FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise _err(ErrorCode.TASK_NOT_FOUND, "Task not found.", task_id=task_id)
            if row["review_required"]:
                raise _err(
                    ErrorCode.TASK_REVIEW_REQUIRED,
                    "Task requires review before a tool call can start.",
                    task_id=task_id,
                    user_action=True,
                )
            if row["status"] != T.RUNNING.value:
                raise _err(
                    ErrorCode.TASK_INVALID,
                    f"Tool call requires RUNNING, task is {row['status']}.",
                    task_id=task_id,
                )
            self._db.insert_row(
                "tool_calls",
                {
                    "id": call_id,
                    "task_id": task_id,
                    "step_id": step_id,
                    "operation": operation,
                    "idempotency_key": idempotency_key,
                    "status": CALL_STARTED,
                    "started_at": now_utc(),
                },
                connection=conn,
            )
        return call_id

    def finish(self, call_id: str, status: str, *, outcome_ref: str = "", error_code: str = "") -> None:
        if status not in (CALL_COMPLETED, CALL_FAILED):
            raise _err(ErrorCode.VALIDATION_FAILED, f"Invalid final tool-call status: {status}")
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tool_calls SET status = ?, finished_at = ?, outcome_ref = ?, error_code = ?"
                " WHERE id = ? AND status = ?",
                (status, now_utc(), outcome_ref, error_code, call_id, CALL_STARTED),
            )
            if cursor.rowcount != 1:
                raise _err(ErrorCode.TASK_INVALID, "Tool call is not in STARTED state.")

    def open_calls(self, task_id: str) -> list[dict[str, Any]]:
        return self._db.query(
            "SELECT id, step_id, operation, idempotency_key, started_at FROM tool_calls"
            " WHERE task_id = ? AND status = ? ORDER BY started_at",
            (task_id, CALL_STARTED),
        )

    def mark_unknown(self, task_id: str) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tool_calls SET status = ?, finished_at = ? WHERE task_id = ? AND status = ?",
                (CALL_UNKNOWN, now_utc(), task_id, CALL_STARTED),
            )
            return int(cursor.rowcount)
