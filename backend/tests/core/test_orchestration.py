# CORE step orchestration tests (S23). Offline; real SQLite and a fake provider.
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from seraphim.aegis import PolicyEngine, PolicyRule, build_policy_set
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.core.approval import APPROVED, CONSUMED, DENIED, EXPIRED, PENDING, ApprovalService
from seraphim.core.orchestration import StepOrchestrator
from seraphim.core.task_machine import Prepare, Start
from seraphim.core.task_model import PlanStep, TaskMode, TaskStatus, create_task
from seraphim.core.task_store import TaskRepository
from seraphim.storage import Database, MigrationRunner
from seraphim.wings import CallStatus, ToolCall, ToolManifest, ToolRegistry

TS = "2026-11-12T10:00:00.000Z"
TOOL = "tool.fs.delete_file"
T = TaskStatus


def _db(root: Path) -> Database:
    db = Database.open(root, environ={})
    MigrationRunner(db).run()
    return db


def _manifest(timeout: int = 5) -> ToolManifest:
    return ToolManifest(
        id=TOOL,
        description="Delete one file (fixture).",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        output_schema={"type": "object"},
        capabilities=("filesystem.delete",),
        risk="high",
        side_effects="destructive",
        permissions=("filesystem.delete",),
        timeout_seconds=timeout,
        supports_cancellation=False,
        idempotency="non_idempotent",
        source="core",
        version="1.0",
    )


class _Provider:
    def __init__(self, hold: threading.Event | None = None, started: threading.Event | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._hold = hold
        self._started = started

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(arguments))
        if self._started is not None:
            self._started.set()
        if self._hold is not None:
            self._hold.wait(5)
        return {"deleted": arguments["path"]}


def _engine(allow: bool = True) -> PolicyEngine:
    rules = [
        PolicyRule(
            rule_id="aegis.user.allow_delete",
            outcome="ALLOW",
            source="user",
            tool_pattern=TOOL,
            priority=10,
        ),
    ] if allow else []
    return PolicyEngine(build_policy_set(tuple(rules)))


@pytest.fixture
def db(test_root: Path) -> Database:
    return _db(test_root)


def _running_task(db: Database, risk_hint: str = "destructive") -> tuple[str, str]:
    step = generate_id("step")
    draft = create_task(
        "delete one file",
        TaskMode.EXECUTE_WITH_APPROVAL,
        (PlanStep(id=step, title="s", verification=("file_exists",), risk_hint=risk_hint),),
        at=TS,
    )
    repo = TaskRepository(db)
    record = repo.insert(draft)
    record = repo.save(record, Prepare(), event_type="TaskPrepared", at=TS)
    repo.save(record, Start(), event_type="TaskStarted", at=TS)
    return draft.id, step


def _call(path: str = "notes/a.txt", task_id: str = "", step_id: str = "") -> ToolCall:
    return ToolCall(
        call_id=generate_id("call"),
        tool_id=TOOL,
        arguments={"path": path},
        task_id=task_id,
        step_id=step_id,
    )


def _orchestrator(db: Database, provider: _Provider, *, allow: bool = True) -> StepOrchestrator:
    registry = ToolRegistry()
    registry.register(_manifest(), provider)
    return StepOrchestrator(db, registry, _engine(allow), actor="tester")


def _status(db: Database, task_id: str) -> TaskStatus:
    return TaskRepository(db).load(task_id).task.status


def test_risky_step_waits_for_decision_and_does_not_run(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    outcome = orch.run_step(
        task_id, step_id, _call(task_id=task_id, step_id=step_id),
        explanation="Delete notes/a.txt", resource="notes/a.txt", risk="high",
    )
    assert outcome.status == T.NEEDS_APPROVAL.value
    assert outcome.approval is not None and outcome.approval.status == PENDING
    assert _status(db, task_id) is T.NEEDS_APPROVAL
    assert provider.calls == []


def test_approved_step_runs_exactly_once(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    done = orch.approve(task_id, step_id, waiting.approval.id, call)
    assert done.result is not None and done.result.status is CallStatus.SUCCEEDED
    assert provider.calls == [{"path": "notes/a.txt"}]
    assert ApprovalService(db).load(waiting.approval.id).status == CONSUMED


def test_denied_approval_never_runs_and_cancels_task(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    orch.deny(task_id, step_id, waiting.approval.id)
    assert provider.calls == []
    assert ApprovalService(db).load(waiting.approval.id).status == DENIED
    assert _status(db, task_id) is T.CANCELLED


def test_duplicate_approval_is_rejected_and_runs_once(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    orch.approve(task_id, step_id, waiting.approval.id, call)
    with pytest.raises(SeraphimError):
        orch.approve(task_id, step_id, waiting.approval.id, call)
    assert len(provider.calls) == 1


def test_approval_cannot_authorise_a_different_operation(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    waiting = orch.run_step(
        task_id, step_id, _call("notes/a.txt", task_id, step_id),
        explanation="e", resource="r", risk="high",
    )
    assert waiting.approval is not None
    with pytest.raises(SeraphimError):
        orch.approve(task_id, step_id, waiting.approval.id, _call("notes/other.txt", task_id, step_id))
    assert provider.calls == []
    assert ApprovalService(db).load(waiting.approval.id).status == APPROVED


def test_expired_approval_cannot_run_the_call(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    db.execute(
        "UPDATE approvals SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00.000Z", waiting.approval.id),
    )
    with pytest.raises(SeraphimError):
        orch.approve(task_id, step_id, waiting.approval.id, call)
    assert provider.calls == []
    assert ApprovalService(db).load(waiting.approval.id).status == EXPIRED


def test_cancel_before_call_prevents_any_new_call(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider, allow=True)
    assert orch.cancel(task_id, "user stopped") is T.CANCELLED
    with pytest.raises(SeraphimError) as exc:
        orch.run_step(task_id, step_id, _call(task_id=task_id, step_id=step_id),
                      explanation="e", resource="r", risk="low")
    assert exc.value.code == ErrorCode.TASK_INVALID
    assert provider.calls == []


def test_cancel_during_call_lets_call_finish_then_reports_cancelled(db):
    task_id, step_id = _running_task(db)
    started = threading.Event()
    hold = threading.Event()
    provider = _Provider(hold=hold, started=started)
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    outcome_box: dict[str, Any] = {}

    def run() -> None:
        outcome_box["outcome"] = orch.approve(task_id, step_id, waiting.approval.id, call)

    worker = threading.Thread(target=run)
    worker.start()
    assert started.wait(5)
    status_during = orch.cancel(task_id, "user stopped")
    assert status_during is T.RUNNING
    assert _status(db, task_id) is T.RUNNING
    hold.set()
    worker.join(5)
    outcome = outcome_box["outcome"]
    assert outcome.status == "CANCEL_AFTER_CALL"
    assert outcome.result is not None and outcome.result.status is CallStatus.SUCCEEDED
    assert _status(db, task_id) is T.CANCELLED
    assert len(provider.calls) == 1


def test_timeout_during_write_reports_failure_not_success(db):
    task_id, step_id = _running_task(db)
    hold = threading.Event()
    registry = ToolRegistry()
    registry.register(_manifest(timeout=1), _Provider(hold=hold))
    orch = StepOrchestrator(db, registry, _engine(True), actor="tester")
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(task_id, step_id, call, explanation="e", resource="r", risk="high")
    assert waiting.approval is not None
    outcome = orch.approve(task_id, step_id, waiting.approval.id, call)
    hold.set()
    assert outcome.result is not None
    assert outcome.result.status is CallStatus.FAILED
    assert outcome.result.error is not None and outcome.result.error.code == ErrorCode.TOOL_TIMEOUT
    assert _status(db, task_id) is T.BLOCKED
    with pytest.raises(SeraphimError) as exc:
        orch.run_step(task_id, step_id, _call(task_id=task_id, step_id=step_id),
                      explanation="e", resource="r", risk="high")
    assert exc.value.code == ErrorCode.TASK_INVALID


def test_ask_user_on_low_risk_hint_step_waits_for_approval(db):
    task_id, step_id = _running_task(db, risk_hint="none")
    provider = _Provider()
    orch = _orchestrator(db, provider)
    outcome = orch.run_step(
        task_id, step_id, _call(task_id=task_id, step_id=step_id),
        explanation="Delete notes/a.txt", resource="notes/a.txt", risk="high",
    )
    assert outcome.status == T.NEEDS_APPROVAL.value
    assert outcome.approval is not None and outcome.approval.status == PENDING
    assert _status(db, task_id) is T.NEEDS_APPROVAL
    assert provider.calls == []


def test_secret_data_is_denied_even_after_approval(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    orch = _orchestrator(db, provider)
    call = _call(task_id=task_id, step_id=step_id)
    waiting = orch.run_step(
        task_id, step_id, call, explanation="e", resource="r", risk="high", data_sensitivity="secret",
    )
    assert waiting.approval is None and waiting.result is not None
    assert waiting.result.status is CallStatus.REJECTED
    assert provider.calls == []


def test_cancel_with_no_gate_decision_does_not_start_call(db):
    task_id, step_id = _running_task(db)
    provider = _Provider()
    registry = ToolRegistry()
    registry.register(_manifest(), provider)
    orch = StepOrchestrator(db, registry, _engine(False), actor="tester")
    outcome = orch.run_step(task_id, step_id, _call(task_id=task_id, step_id=step_id),
                            explanation="e", resource="r", risk="low")
    assert outcome.approval is not None or outcome.result is not None
    assert provider.calls == []
