# CORE task model (S16): typed Task, PlanStep and verification evidence.
# Pure data. All state changes go through task_machine.transition().

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from seraphim.contracts.constants import SIDE_EFFECTS, STEP_STATES, TASK_STATES
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id, validate_id
from seraphim.contracts.timestamps import validate_timestamp

COMPONENT = "core.task_model"
TASK_SCOPE = "task"


class TaskMode(StrEnum):
    OBSERVE = "observe"
    ASSIST = "assist"
    EXECUTE_WITH_APPROVAL = "execute_with_approval"
    AUTONOMOUS_WITHIN_POLICY = "autonomous_within_policy"


class TaskStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


assert {s.value for s in TaskStatus} == set(TASK_STATES)
assert {s.value for s in StepStatus} == set(STEP_STATES)

TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED}
)
DONE_STEP_STATUSES = frozenset({StepStatus.SUCCEEDED, StepStatus.SKIPPED})


def _invalid(message: str) -> SeraphimError:
    return SeraphimError(code=ErrorCode.TASK_INVALID, component=COMPONENT, safe_message=message)


def _plan_invalid(message: str) -> SeraphimError:
    return SeraphimError(
        code=ErrorCode.PLAN_VALIDATION_FAILED, component=COMPONENT, safe_message=message
    )


@dataclass(frozen=True)
class CheckOutcome:
    """One verification check. A passing check must cite the evidence it relied on."""

    name: str
    passed: bool
    evidence_ref: str = ""
    available: bool = True
    source: str = ""
    observed_at: str = ""
    mandatory: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise _invalid("Check name must not be empty")
        if self.passed and not self.evidence_ref:
            raise _invalid(f"Passing check {self.name!r} must reference evidence")


@dataclass(frozen=True)
class VerificationReport:
    """Result of a verification procedure run by the Verification Engine, not by the model.

    ``passed`` is true only when at least one check ran and every check passed,
    so an empty procedure can never count as success.
    """

    verifier_id: str
    checks: tuple[CheckOutcome, ...]

    def __post_init__(self) -> None:
        if not self.verifier_id:
            raise _invalid("Verification report must name its verifier")
        if not isinstance(self.checks, tuple):
            raise _invalid("Verification checks must be a tuple")

    @property
    def status(self) -> str:
        required = tuple(c for c in self.checks if c.mandatory)
        if any(c.available and not c.passed for c in required):
            return "failed"
        if required and all(c.available and c.passed for c in required):
            return "verified"
        if any(c.passed for c in self.checks):
            return "partially_verified"
        return "unverified"

    @property
    def passed(self) -> bool:
        return self.status == "verified"


@dataclass(frozen=True)
class PlanStep:
    id: str
    title: str
    verification: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    max_attempts: int = 1
    requires_approval: bool = False
    risk_hint: str = "none"
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    report: VerificationReport | None = None
    required_tools: tuple[str, ...] = ()
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.id)
        if not self.title:
            raise _plan_invalid(f"Step {self.id} has no title")
        if not self.verification:
            raise _plan_invalid(f"Step {self.id} has no verification criteria")
        if self.max_attempts < 1:
            raise _plan_invalid(f"Step {self.id} must allow at least one attempt")
        if self.risk_hint not in SIDE_EFFECTS:
            raise _plan_invalid(f"Step {self.id} has unknown risk hint {self.risk_hint!r}")
        if self.id in self.depends_on:
            raise _plan_invalid(f"Step {self.id} depends on itself")
        if self.status is StepStatus.SUCCEEDED and (self.report is None or not self.report.passed):
            raise _invalid(f"Step {self.id} is SUCCEEDED without a passing report")


@dataclass(frozen=True)
class TaskResult:
    outcome: TaskStatus
    reason: str = ""
    error_code: str = ""
    verification: VerificationReport | None = None

    def __post_init__(self) -> None:
        if self.outcome not in TERMINAL_TASK_STATUSES:
            raise _invalid(f"Result outcome must be terminal, got {self.outcome}")
        if self.outcome in (TaskStatus.BLOCKED, TaskStatus.CANCELLED) and not self.reason:
            raise _invalid(f"{self.outcome} result requires a reason")
        if self.outcome is TaskStatus.FAILED and not (self.reason or self.error_code):
            raise _invalid("FAILED result requires a reason or error code")
        if self.outcome is TaskStatus.SUCCEEDED and (
            self.verification is None or not self.verification.passed
        ):
            raise _invalid("SUCCEEDED result requires a passing verification report")


@dataclass(frozen=True)
class Task:
    id: str
    goal: str
    mode: TaskMode
    steps: tuple[PlanStep, ...]
    updated_at: str
    constraints: tuple[str, ...] = ()
    status: TaskStatus = TaskStatus.DRAFT
    result: TaskResult | None = None
    pending_verification: str = ""
    pending_approval_step: str = ""
    approved_step_id: str = ""

    def step(self, step_id: str) -> PlanStep:
        for candidate in self.steps:
            if candidate.id == step_id:
                return candidate
        raise _invalid(f"Unknown step {step_id!r}")

    def with_step(self, updated: PlanStep) -> Task:
        steps = tuple(updated if s.id == updated.id else s for s in self.steps)
        return replace(self, steps=steps)


def create_task(
    goal: str,
    mode: TaskMode,
    steps: tuple[PlanStep, ...],
    *,
    at: str,
    task_id: str = "",
    constraints: tuple[str, ...] = (),
) -> Task:
    """Validate a structured plan and return a DRAFT task. Raises SeraphimError."""
    if not goal:
        raise _plan_invalid("Task goal must not be empty")
    if not steps:
        raise _plan_invalid("Plan must contain at least one step")
    validate_timestamp(at)
    ids = [step.id for step in steps]
    if len(set(ids)) != len(ids):
        raise _plan_invalid("Plan step ids must be unique")
    known = set(ids)
    for step in steps:
        missing = [dep for dep in step.depends_on if dep not in known]
        if missing:
            raise _plan_invalid(f"Step {step.id} depends on unknown steps")
    _ensure_acyclic(steps)
    task_id = task_id or generate_id("task")
    validate_id(task_id)
    return Task(
        id=task_id, goal=goal, mode=mode, steps=steps, updated_at=at, constraints=tuple(constraints)
    )


def _ensure_acyclic(steps: tuple[PlanStep, ...]) -> None:
    graph = {step.id: step.depends_on for step in steps}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in visiting:
            raise _plan_invalid("Plan dependencies contain a cycle")
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.discard(node)
        done.add(node)

    for node in graph:
        visit(node)


def check_invariants(task: Task) -> None:
    """Raise SeraphimError if the task violates a state invariant."""
    terminal = task.status in TERMINAL_TASK_STATUSES
    if terminal != (task.result is not None):
        raise _invalid(f"Task {task.status} and result presence disagree")
    if task.result is not None and task.result.outcome is not task.status:
        raise _invalid("Task result outcome does not match task status")
    if task.status is TaskStatus.SUCCEEDED and not all(
        s.status in DONE_STEP_STATUSES for s in task.steps
    ):
        raise _invalid("SUCCEEDED requires every step to be SUCCEEDED or SKIPPED")
    if task.status is TaskStatus.VERIFYING and not task.pending_verification:
        raise _invalid("VERIFYING requires a pending verification target")
    if task.status is not TaskStatus.VERIFYING and task.pending_verification:
        raise _invalid("Pending verification is only valid in VERIFYING")
    if task.status is TaskStatus.NEEDS_APPROVAL and not task.pending_approval_step:
        raise _invalid("NEEDS_APPROVAL requires a pending approval step")
    if task.status is not TaskStatus.NEEDS_APPROVAL and task.pending_approval_step:
        raise _invalid("Pending approval is only valid in NEEDS_APPROVAL")
    if task.status is TaskStatus.RETRYING and not has_retry_budget(task):
        raise _invalid("RETRYING requires a failed step with attempts left")


def has_retry_budget(task: Task) -> bool:
    return any(s.status is StepStatus.FAILED and s.attempts < s.max_attempts for s in task.steps)
