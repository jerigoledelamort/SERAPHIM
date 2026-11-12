# CORE task service (S17): list/show/pause/resume/cancel and startup recovery.
#
# Every status change goes through task_machine.transition() and is persisted by
# TaskRepository.save(). Nothing here runs a step or calls a tool: resume only
# moves the state machine, so repeated resume cannot repeat work.

from __future__ import annotations

from dataclasses import dataclass, field

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.timestamps import now_utc
from seraphim.core.task_machine import Cancel, Pause, Resume
from seraphim.core.task_model import TaskStatus
from seraphim.core.task_store import TaskRecord, TaskRepository, ToolCallLedger
from seraphim.storage.db import Database

T = TaskStatus

REVIEW_TOOL_CALL = "open tool call with unknown outcome after restart"
REVIEW_UNRESUMABLE = "status cannot be continued after restart"


@dataclass(frozen=True)
class RecoveryReport:
    checked: int
    paused: tuple[str, ...] = ()
    flagged_for_review: tuple[str, ...] = field(default=())


class TaskService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._tasks = TaskRepository(db)
        self._calls = ToolCallLedger(db)

    @property
    def tasks(self) -> TaskRepository:
        return self._tasks

    @property
    def calls(self) -> ToolCallLedger:
        return self._calls

    def list(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        return self._tasks.list_tasks(status=status)

    def show(self, task_id: str) -> TaskRecord:
        return self._tasks.load(task_id)

    def pause(self, task_id: str) -> TaskRecord:
        return self._apply(task_id, Pause(), "TaskPaused")

    def resume(self, task_id: str) -> TaskRecord:
        record = self._tasks.load(task_id)
        if record.review_required:
            raise SeraphimError(
                code=ErrorCode.TASK_REVIEW_REQUIRED,
                component="core.task_service",
                safe_message=f"Task needs review first: {record.review_reason}.",
                task_id=task_id,
                user_action_required=True,
            )
        if record.task.status is not T.PAUSED:
            raise SeraphimError(
                code=ErrorCode.TASK_INVALID,
                component="core.task_service",
                safe_message=f"Resume requires PAUSED, task is {record.task.status.value}.",
                task_id=task_id,
            )
        return self._apply(task_id, Resume(), "TaskResumed")

    def cancel(self, task_id: str, reason: str) -> TaskRecord:
        return self._apply(task_id, Cancel(reason), "TaskCancelled", allow_review=True)

    def review_clear(self, task_id: str, *, note: str) -> TaskRecord:
        return self._tasks.set_review(task_id, required=False, reason=note, at=now_utc())

    def recover(self) -> RecoveryReport:
        """Check every unfinished task after a restart and route the unsafe ones to review."""
        unfinished = [
            r for r in self._tasks.list_tasks()
            if r.task.status not in (T.SUCCEEDED, T.FAILED, T.CANCELLED, T.BLOCKED)
        ]
        paused: list[str] = []
        flagged: list[str] = []
        for record in unfinished:
            task_id = record.task.id
            if self._calls.open_calls(task_id):
                self._calls.mark_unknown(task_id)
                self._tasks.set_review(task_id, required=True, reason=REVIEW_TOOL_CALL, at=now_utc())
                flagged.append(task_id)
                continue
            if record.review_required:
                flagged.append(task_id)
                continue
            if record.task.status in (T.RUNNING, T.VERIFYING, T.NEEDS_APPROVAL, T.RETRYING):
                self._tasks.set_review(task_id, required=True, reason=REVIEW_UNRESUMABLE, at=now_utc())
                flagged.append(task_id)
                continue
            if record.task.status is T.PAUSED:
                paused.append(task_id)
        return RecoveryReport(
            checked=len(unfinished),
            paused=tuple(paused),
            flagged_for_review=tuple(flagged),
        )

    def _apply(self, task_id: str, event: object, event_type: str, *, allow_review: bool = False) -> TaskRecord:
        record = self._tasks.load(task_id)
        if record.review_required and not allow_review:
            raise SeraphimError(
                code=ErrorCode.TASK_REVIEW_REQUIRED,
                component="core.task_service",
                safe_message=f"Task needs review first: {record.review_reason}.",
                task_id=task_id,
                user_action_required=True,
            )
        return self._tasks.save(record, event, event_type=event_type, at=now_utc())
