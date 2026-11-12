# CORE task state machine (S16). The only place where Task.status may change.
#
# transition() accepts a typed event, checks it against ALLOWED, applies it and
# re-checks invariants. Nothing here reads model output: events carry only
# identifiers and VerificationReports built by the verifier.

from __future__ import annotations

from dataclasses import dataclass, replace

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.timestamps import validate_timestamp
from seraphim.core.task_model import (
    COMPONENT,
    TASK_SCOPE,
    TERMINAL_TASK_STATUSES,
    PlanStep,
    StepStatus,
    Task,
    TaskMode,
    TaskResult,
    TaskStatus,
    VerificationReport,
    check_invariants,
    has_retry_budget,
)

T = TaskStatus
HIGH_RISK_HINTS = frozenset({"external", "destructive"})


@dataclass(frozen=True)
class Prepare:
    pass


@dataclass(frozen=True)
class Start:
    pass


@dataclass(frozen=True)
class StartStep:
    step_id: str
    needs_approval: bool = False


@dataclass(frozen=True)
class Approve:
    step_id: str


@dataclass(frozen=True)
class RejectApproval:
    step_id: str


@dataclass(frozen=True)
class FailStep:
    step_id: str


@dataclass(frozen=True)
class SubmitStep:
    step_id: str


@dataclass(frozen=True)
class SubmitTask:
    pass


@dataclass(frozen=True)
class Verified:
    target: str
    report: VerificationReport


@dataclass(frozen=True)
class Retry:
    step_id: str


@dataclass(frozen=True)
class Pause:
    pass


@dataclass(frozen=True)
class Resume:
    pass


@dataclass(frozen=True)
class Cancel:
    reason: str


@dataclass(frozen=True)
class Block:
    reason: str


@dataclass(frozen=True)
class Fail:
    error_code: str
    reason: str


Event = (
    Prepare | Start | StartStep | Approve | RejectApproval | FailStep | SubmitStep | SubmitTask
    | Verified | Retry | Pause | Resume | Cancel | Block | Fail
)

# (from_status, event_type) -> allowed target statuses. Guards inside handlers
# may still reject an otherwise allowed edge.
ALLOWED: dict[tuple[TaskStatus, type], frozenset[TaskStatus]] = {
    (T.DRAFT, Prepare): frozenset({T.READY}),
    (T.READY, Start): frozenset({T.RUNNING}),
    (T.RUNNING, StartStep): frozenset({T.RUNNING, T.NEEDS_APPROVAL}),
    (T.NEEDS_APPROVAL, Approve): frozenset({T.RUNNING}),
    (T.NEEDS_APPROVAL, RejectApproval): frozenset({T.CANCELLED}),
    (T.RUNNING, FailStep): frozenset({T.RETRYING, T.FAILED}),
    (T.RUNNING, SubmitStep): frozenset({T.VERIFYING}),
    (T.RUNNING, SubmitTask): frozenset({T.VERIFYING}),
    (T.VERIFYING, Verified): frozenset({T.RUNNING, T.RETRYING, T.FAILED, T.SUCCEEDED}),
    (T.RETRYING, Retry): frozenset({T.RUNNING}),
    (T.RUNNING, Pause): frozenset({T.PAUSED}),
    (T.RETRYING, Pause): frozenset({T.PAUSED}),
    (T.NEEDS_APPROVAL, Pause): frozenset({T.PAUSED}),
    (T.PAUSED, Resume): frozenset({T.RUNNING, T.RETRYING}),
    (T.RUNNING, Block): frozenset({T.BLOCKED}),
    (T.RETRYING, Block): frozenset({T.BLOCKED}),
    (T.NEEDS_APPROVAL, Block): frozenset({T.BLOCKED}),
    (T.PAUSED, Block): frozenset({T.BLOCKED}),
    (T.VERIFYING, Block): frozenset({T.BLOCKED}),
    (T.PAUSED, Fail): frozenset({T.FAILED}),
    (T.RUNNING, Fail): frozenset({T.FAILED}),
    (T.RETRYING, Fail): frozenset({T.FAILED}),
    (T.VERIFYING, Fail): frozenset({T.FAILED}),
    (T.NEEDS_APPROVAL, Fail): frozenset({T.FAILED}),
    (T.READY, Cancel): frozenset({T.CANCELLED}),
    (T.RUNNING, Cancel): frozenset({T.CANCELLED}),
    (T.VERIFYING, Cancel): frozenset({T.CANCELLED}),
    (T.RETRYING, Cancel): frozenset({T.CANCELLED}),
    (T.PAUSED, Cancel): frozenset({T.CANCELLED}),
    (T.NEEDS_APPROVAL, Cancel): frozenset({T.CANCELLED}),
}


def _rejected(task: Task, event: object, why: str) -> SeraphimError:
    return SeraphimError(
        code=ErrorCode.TASK_INVALID,
        component=COMPONENT,
        task_id=task.id,
        safe_message=f"{type(event).__name__} rejected in {task.status}: {why}",
    )


def _is_allowed(status: TaskStatus, event: object) -> bool:
    return (status, type(event)) in ALLOWED


def _step_ready(task: Task, step: PlanStep) -> bool:
    done = {s.id for s in task.steps if s.status is StepStatus.SUCCEEDED}
    return all(dep in done for dep in step.depends_on)


def _set_step(task: Task, step: PlanStep, **changes) -> Task:
    return task.with_step(replace(step, **changes))


def _finish(task: Task, status: TaskStatus, result: TaskResult | None, at: str, **changes) -> Task:
    return replace(task, status=status, result=result, updated_at=at, **changes)


def _apply(task: Task, event: object, at: str) -> Task:
    if isinstance(event, Prepare):
        return _finish(task, T.READY, None, at)

    if isinstance(event, Start):
        return _finish(task, T.RUNNING, None, at)

    if isinstance(event, StartStep):
        step = task.step(event.step_id)
        if step.status not in (StepStatus.PENDING, StepStatus.READY):
            raise _rejected(task, event, f"step {step.id} is {step.status}")
        if not _step_ready(task, step):
            raise _rejected(task, event, f"step {step.id} has unfinished dependencies")
        if task.mode is TaskMode.OBSERVE and step.risk_hint not in ("none", "read"):
            raise _rejected(task, event, f"step {step.id} changes state and OBSERVE mode forbids it")
        needs_approval = event.needs_approval or step.requires_approval or step.risk_hint in HIGH_RISK_HINTS
        if needs_approval and task.approved_step_id != step.id:
            return _finish(task, T.NEEDS_APPROVAL, None, at, pending_approval_step=step.id)
        started = _set_step(task, step, status=StepStatus.RUNNING, attempts=step.attempts + 1)
        return _finish(started, T.RUNNING, None, at, approved_step_id="")

    if isinstance(event, Approve):
        if task.pending_approval_step != event.step_id:
            raise _rejected(task, event, "approval does not match the pending step")
        return _finish(
            task, T.RUNNING, None, at, pending_approval_step="", approved_step_id=event.step_id
        )

    if isinstance(event, RejectApproval):
        if task.pending_approval_step != event.step_id:
            raise _rejected(task, event, "approval does not match the pending step")
        return _finish(
            task,
            T.CANCELLED,
            TaskResult(outcome=T.CANCELLED, reason="approval rejected"),
            at,
            pending_approval_step="",
        )

    if isinstance(event, SubmitStep):
        step = task.step(event.step_id)
        if step.status is not StepStatus.RUNNING:
            raise _rejected(task, event, f"step {step.id} is not running")
        return _finish(task, T.VERIFYING, None, at, pending_verification=step.id)

    if isinstance(event, SubmitTask):
        if not all(s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for s in task.steps):
            raise _rejected(task, event, "not every step is complete")
        return _finish(task, T.VERIFYING, None, at, pending_verification=TASK_SCOPE)

    if isinstance(event, Verified):
        return _apply_verified(task, event, at)

    if isinstance(event, FailStep):
        step = task.step(event.step_id)
        if step.status is not StepStatus.RUNNING:
            raise _rejected(task, event, f"step {step.id} is not running")
        failed = _set_step(task, step, status=StepStatus.FAILED)
        return _after_step_failure(failed, step.id, at, "step failed", "")

    if isinstance(event, Retry):
        step = task.step(event.step_id)
        if step.status is not StepStatus.FAILED or step.attempts >= step.max_attempts:
            raise _rejected(task, event, f"step {step.id} has no retry budget")
        reset = _set_step(task, step, status=StepStatus.PENDING, report=None)
        return _finish(reset, T.RUNNING, None, at)

    if isinstance(event, Pause):
        return _finish(task, T.PAUSED, None, at, pending_approval_step="")

    if isinstance(event, Resume):
        target = T.RETRYING if has_retry_budget(task) else T.RUNNING
        return _finish(task, target, None, at)

    if isinstance(event, Cancel):
        return _terminal(task, T.CANCELLED, event.reason, "", at)

    if isinstance(event, Block):
        return _terminal(task, T.BLOCKED, event.reason, "", at)

    if isinstance(event, Fail):
        return _terminal(task, T.FAILED, event.reason, event.error_code, at)

    raise _rejected(task, event, "unknown event")


def _apply_verified(task: Task, event: Verified, at: str) -> Task:
    if task.pending_verification != event.target:
        raise _rejected(task, event, "verification target does not match the pending target")
    if event.target == TASK_SCOPE:
        if not event.report.passed:
            return _after_task_verification_failure(task, event.report, at)
        result = TaskResult(outcome=T.SUCCEEDED, verification=event.report)
        return _finish(task, T.SUCCEEDED, result, at, pending_verification="")
    step = task.step(event.target)
    if event.report.passed:
        done = _set_step(task, step, status=StepStatus.SUCCEEDED, report=event.report)
        return _finish(done, T.RUNNING, None, at, pending_verification="")
    failed = _set_step(task, step, status=StepStatus.FAILED, report=event.report)
    return _after_step_failure(failed, step.id, at, "step verification failed", "", clear=True)


def _after_step_failure(
    task: Task, step_id: str, at: str, reason: str, error_code: str, *, clear: bool = False
) -> Task:
    step = task.step(step_id)
    base = {"pending_verification": ""} if clear else {}
    if step.attempts < step.max_attempts:
        return _finish(task, T.RETRYING, None, at, **base)
    result = TaskResult(outcome=T.FAILED, reason=f"{reason}: {step_id}", error_code=error_code)
    return _finish(task, T.FAILED, result, at, **base)


def _after_task_verification_failure(task: Task, report: VerificationReport, at: str) -> Task:
    result = TaskResult(
        outcome=T.FAILED, reason="task verification failed", verification=report
    )
    return _finish(task, T.FAILED, result, at, pending_verification="")


def _terminal(task: Task, status: TaskStatus, reason: str, error_code: str, at: str) -> Task:
    result = TaskResult(outcome=status, reason=reason, error_code=error_code)
    return _finish(task, status, result, at, pending_verification="", pending_approval_step="")


def transition(task: Task, event: object, *, at: str) -> Task:
    """Apply *event* to *task* and return the new task. Raises SeraphimError on any illegal edge."""
    validate_timestamp(at)
    if task.status in TERMINAL_TASK_STATUSES:
        raise _rejected(task, event, "task is terminal")
    if not _is_allowed(task.status, event):
        raise _rejected(task, event, "transition not in the allowed table")
    new_task = _apply(task, event, at)
    if new_task.status not in ALLOWED[(task.status, type(event))]:
        raise _rejected(task, event, "handler produced a disallowed target")
    check_invariants(new_task)
    return new_task
