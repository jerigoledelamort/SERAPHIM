# CORE task state machine tests (S16). Offline, no model, no I/O.

from __future__ import annotations

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.core.task_machine import (
    ALLOWED,
    Approve,
    Block,
    Cancel,
    Fail,
    FailStep,
    Pause,
    Prepare,
    RejectApproval,
    RequestApproval,
    Resume,
    Retry,
    Start,
    StartStep,
    SubmitStep,
    SubmitTask,
    Verified,
    transition,
)
from seraphim.core.task_model import (
    TASK_SCOPE,
    CheckOutcome,
    PlanStep,
    StepStatus,
    Task,
    TaskMode,
    TaskResult,
    TaskStatus,
    VerificationReport,
    check_invariants,
    create_task,
)

TS = "2026-11-12T10:00:00.000Z"
S1 = generate_id("step")
S2 = generate_id("step")
PASS = VerificationReport("verifier.fixture", (CheckOutcome("file_exists", True, "evidence_1"),))
FAIL = VerificationReport("verifier.fixture", (CheckOutcome("file_exists", False),))
EMPTY = VerificationReport("verifier.fixture", ())
T = TaskStatus


def _step(sid, *, attempts=1, approval=False, depends=()):
    return PlanStep(
        id=sid,
        title="step",
        verification=("file_exists",),
        depends_on=depends,
        max_attempts=attempts,
        requires_approval=approval,
    )


def _task(*steps) -> Task:
    return create_task("goal", TaskMode.EXECUTE_WITH_APPROVAL, steps, at=TS)


def _run(task: Task, *events) -> Task:
    for event in events:
        task = transition(task, event, at=TS)
    return task


def _ready(*steps) -> Task:
    return _run(_task(*steps or (_step(S1),)), Prepare(), Start())


def _in_status(status: TaskStatus) -> Task:
    """Reachable task fixture for every status, built only through transition()."""
    if status is T.DRAFT:
        return _task(_step(S1))
    if status is T.READY:
        return _run(_task(_step(S1)), Prepare())
    if status is T.RUNNING:
        return _ready()
    if status is T.VERIFYING:
        return _run(_ready(), StartStep(S1), SubmitStep(S1))
    if status is T.NEEDS_APPROVAL:
        return _run(_ready(_step(S1, approval=True)), StartStep(S1))
    if status is T.RETRYING:
        return _run(_ready(_step(S1, attempts=2)), StartStep(S1), FailStep(S1))
    if status is T.PAUSED:
        return _run(_ready(), Pause())
    if status is T.SUCCEEDED:
        return _run(_ready(), StartStep(S1), SubmitStep(S1), Verified(S1, PASS), SubmitTask(),
                    Verified(TASK_SCOPE, PASS))
    if status is T.FAILED:
        return _run(_ready(), Fail("TASK_FIXTURE", "fixture failure"))
    if status is T.CANCELLED:
        return _run(_ready(), Cancel("fixture cancel"))
    if status is T.BLOCKED:
        return _run(_ready(), Block("fixture block"))
    raise AssertionError(status)


ALL_EVENTS = [
    Prepare(), Start(), StartStep(S1), Approve(S1), RejectApproval(S1), FailStep(S1),
    SubmitStep(S1), SubmitTask(), Verified(S1, PASS), Retry(S1), Pause(), Resume(),
    Cancel("r"), Block("r"), Fail("E", "r"),
]


@pytest.mark.parametrize("status", list(TaskStatus), ids=lambda s: s.value)
def test_fixture_reaches_status(status):
    assert _in_status(status).status is status


@pytest.mark.parametrize("status", list(TaskStatus), ids=lambda s: s.value)
def test_every_non_allowed_event_is_rejected(status):
    task = _in_status(status)
    rejected = 0
    for event in ALL_EVENTS:
        if (status, type(event)) in ALLOWED:
            continue
        rejected += 1
        with pytest.raises(SeraphimError) as exc:
            transition(task, event, at=TS)
        assert exc.value.code == ErrorCode.TASK_INVALID
    assert rejected > 0


def _plain_running():
    return _ready()


def _approval_running():
    return _ready(_step(S1, approval=True))


def _retry_running():
    return _run(_ready(_step(S1, attempts=2)), StartStep(S1))


def _verifying(attempts=2):
    return _run(_ready(_step(S1, attempts=attempts)), StartStep(S1), SubmitStep(S1))


def _verifying_task_scope():
    return _run(_verifying(attempts=1), Verified(S1, PASS), SubmitTask())


def _needs_approval():
    return _run(_approval_running(), StartStep(S1))


# (fixture, event, expected target): every edge in ALLOWED is listed once.
DOCUMENTED_EDGES = [
    (lambda: _task(_step(S1)), Prepare(), T.READY),
    (lambda: _run(_task(_step(S1)), Prepare()), Start(), T.RUNNING),
    (_plain_running, StartStep(S1), T.RUNNING),
    (_approval_running, StartStep(S1), T.NEEDS_APPROVAL),
    (_needs_approval, Approve(S1), T.RUNNING),
    (lambda: _run(_ready(), StartStep(S1)), RequestApproval(S1), T.NEEDS_APPROVAL),
    (_needs_approval, RejectApproval(S1), T.CANCELLED),
    (_retry_running, FailStep(S1), T.RETRYING),
    (lambda: _run(_ready(), StartStep(S1)), FailStep(S1), T.FAILED),
    (lambda: _run(_ready(), StartStep(S1)), SubmitStep(S1), T.VERIFYING),
    (lambda: _run(_ready(), StartStep(S1), SubmitStep(S1), Verified(S1, PASS)), SubmitTask(), T.VERIFYING),
    (lambda: _verifying(attempts=1), Verified(S1, PASS), T.RUNNING),
    (lambda: _verifying(attempts=2), Verified(S1, FAIL), T.RETRYING),
    (lambda: _verifying(attempts=1), Verified(S1, FAIL), T.FAILED),
    (_verifying_task_scope, Verified(TASK_SCOPE, PASS), T.SUCCEEDED),
    (_verifying_task_scope, Verified(TASK_SCOPE, FAIL), T.FAILED),
    (lambda: _run(_retry_running(), FailStep(S1)), Retry(S1), T.RUNNING),
    (_plain_running, Pause(), T.PAUSED),
    (lambda: _in_status(T.RETRYING), Pause(), T.PAUSED),
    (_needs_approval, Pause(), T.PAUSED),
    (lambda: _run(_ready(), Pause()), Resume(), T.RUNNING),
    (lambda: _in_status(T.PAUSED), Resume(), T.RUNNING),
    (lambda: _run(_in_status(T.RETRYING), Pause()), Resume(), T.RETRYING),
    (_plain_running, Block("r"), T.BLOCKED),
    (lambda: _in_status(T.RETRYING), Block("r"), T.BLOCKED),
    (_needs_approval, Block("r"), T.BLOCKED),
    (lambda: _run(_ready(), Pause()), Block("r"), T.BLOCKED),
    (lambda: _verifying(attempts=1), Block("r"), T.BLOCKED),
    (_plain_running, Fail("E", "r"), T.FAILED),
    (lambda: _in_status(T.RETRYING), Fail("E", "r"), T.FAILED),
    (lambda: _verifying(attempts=1), Fail("E", "r"), T.FAILED),
    (_needs_approval, Fail("E", "r"), T.FAILED),
    (lambda: _run(_ready(), Pause()), Fail("E", "r"), T.FAILED),
    (lambda: _in_status(T.READY), Cancel("r"), T.CANCELLED),
    (_plain_running, Cancel("r"), T.CANCELLED),
    (lambda: _verifying(attempts=1), Cancel("r"), T.CANCELLED),
    (lambda: _in_status(T.RETRYING), Cancel("r"), T.CANCELLED),
    (lambda: _run(_ready(), Pause()), Cancel("r"), T.CANCELLED),
    (_needs_approval, Cancel("r"), T.CANCELLED),
]


def test_documented_edges_cover_the_whole_allowed_table():
    covered = {(type(event), target) for _, event, target in DOCUMENTED_EDGES}
    table = {(edge_type, target) for (_, edge_type), targets in ALLOWED.items() for target in targets}
    assert covered == table


@pytest.mark.parametrize(
    ("fixture", "event", "expected"),
    DOCUMENTED_EDGES,
    ids=[f"{type(e).__name__}->{t.value}" for _, e, t in DOCUMENTED_EDGES],
)
def test_documented_edge(fixture, event, expected):
    source = fixture()
    target = transition(source, event, at=TS)
    assert target.status is expected
    assert target.status in ALLOWED[(source.status, type(event))]
    assert target.updated_at == TS


def test_success_path_requires_step_and_task_verification():
    task = _run(_ready(), StartStep(S1), SubmitStep(S1), Verified(S1, PASS), SubmitTask())
    assert task.status is T.VERIFYING
    assert task.pending_verification == TASK_SCOPE
    done = transition(task, Verified(TASK_SCOPE, PASS), at=TS)
    assert done.status is T.SUCCEEDED
    assert done.result is not None and done.result.verification is not None
    assert done.result.verification.passed
    assert all(s.status is StepStatus.SUCCEEDED for s in done.steps)


def test_submit_task_rejected_while_a_step_is_open():
    with pytest.raises(SeraphimError) as exc:
        transition(_ready(), SubmitTask(), at=TS)
    assert exc.value.code == ErrorCode.TASK_INVALID


@pytest.mark.parametrize("report", [EMPTY, FAIL], ids=["empty", "failing"])
def test_task_verification_without_passing_report_never_succeeds(report):
    task = _verifying_task_scope()
    result = transition(task, Verified(TASK_SCOPE, report), at=TS)
    assert result.status is T.FAILED
    assert result.result.outcome is T.FAILED


def test_verified_with_wrong_target_is_rejected():
    with pytest.raises(SeraphimError) as exc:
        transition(_verifying(), Verified(TASK_SCOPE, PASS), at=TS)
    assert exc.value.code == ErrorCode.TASK_INVALID


def test_step_verification_failure_retries_until_budget_exhausted():
    retrying = transition(_verifying(attempts=2), Verified(S1, FAIL), at=TS)
    assert retrying.status is T.RETRYING
    assert retrying.step(S1).status is StepStatus.FAILED
    assert retrying.step(S1).report is FAIL
    again = _run(retrying, Retry(S1), StartStep(S1), SubmitStep(S1))
    failed = transition(again, Verified(S1, FAIL), at=TS)
    assert failed.status is T.FAILED
    assert failed.result.error_code == ""
    assert "step verification failed" in failed.result.reason


def test_retry_rejected_without_budget():
    failed = _run(_ready(), StartStep(S1), FailStep(S1))
    assert failed.status is T.FAILED
    with pytest.raises(SeraphimError):
        transition(failed, Retry(S1), at=TS)


def test_approval_is_bound_to_one_step_and_one_start():
    waiting = _run(_ready(_step(S1, approval=True, attempts=2)), StartStep(S1))
    assert waiting.status is T.NEEDS_APPROVAL
    with pytest.raises(SeraphimError):
        transition(waiting, Approve(S2), at=TS)
    running = transition(waiting, Approve(S1), at=TS)
    assert running.status is T.RUNNING
    started = transition(running, StartStep(S1), at=TS)
    assert started.step(S1).status is StepStatus.RUNNING
    assert started.approved_step_id == ""
    retrying = _run(started, FailStep(S1))
    assert retrying.status is T.RETRYING


def test_pause_during_retry_resumes_into_retry_not_a_dead_end():
    retrying = _in_status(T.RETRYING)
    paused = transition(retrying, Pause(), at=TS)
    resumed = transition(paused, Resume(), at=TS)
    assert resumed.status is T.RETRYING
    again = _run(resumed, Retry(S1), StartStep(S1), SubmitStep(S1))
    assert again.status is T.VERIFYING


def test_pause_from_approval_drops_the_pending_approval():
    paused = transition(_needs_approval(), Pause(), at=TS)
    assert paused.status is T.PAUSED
    assert paused.pending_approval_step == ""


def test_approval_cannot_be_reused_after_retry():
    task = _run(_ready(_step(S1, approval=True, attempts=2)), StartStep(S1), Approve(S1))
    task = _run(task, StartStep(S1), FailStep(S1), Retry(S1))
    assert task.status is T.RUNNING
    assert task.step(S1).status is StepStatus.PENDING
    waiting = transition(task, StartStep(S1), at=TS)
    assert waiting.status is T.NEEDS_APPROVAL


def test_reject_approval_cancels_with_reason():
    cancelled = transition(_needs_approval(), RejectApproval(S1), at=TS)
    assert cancelled.status is T.CANCELLED
    assert cancelled.result.reason == "approval rejected"
    assert cancelled.pending_approval_step == ""


def test_dependency_blocks_start_until_predecessor_succeeded():
    task = _ready(_step(S1), _step(S2, depends=(S1,)))
    with pytest.raises(SeraphimError):
        transition(task, StartStep(S2), at=TS)


def test_terminal_outcomes_are_distinct_and_carry_their_evidence():
    failed = _in_status(T.FAILED).result
    cancelled = _in_status(T.CANCELLED).result
    blocked = _in_status(T.BLOCKED).result
    assert (failed.outcome, cancelled.outcome, blocked.outcome) == (T.FAILED, T.CANCELLED, T.BLOCKED)
    assert failed.error_code == "TASK_FIXTURE" and failed.reason
    assert cancelled.error_code == "" and cancelled.reason
    assert blocked.error_code == "" and blocked.reason


@pytest.mark.parametrize("status", [T.SUCCEEDED, T.FAILED, T.CANCELLED, T.BLOCKED], ids=lambda s: s.value)
def test_terminal_states_accept_no_event(status):
    task = _in_status(status)
    for event in ALL_EVENTS:
        with pytest.raises(SeraphimError):
            transition(task, event, at=TS)


def test_pause_and_resume_keep_steps_intact():
    running = _run(_ready(), StartStep(S1))
    paused = transition(running, Pause(), at=TS)
    assert paused.status is T.PAUSED
    assert paused.step(S1).status is StepStatus.RUNNING
    resumed = transition(paused, Resume(), at=TS)
    assert resumed.status is T.RUNNING


def test_cancel_during_verification_clears_pending_target():
    cancelled = transition(_verifying(), Cancel("user stopped"), at=TS)
    assert cancelled.status is T.CANCELLED
    assert cancelled.pending_verification == ""


def test_succeeded_without_verification_is_impossible_to_construct():
    with pytest.raises(SeraphimError):
        TaskResult(outcome=T.SUCCEEDED)
    with pytest.raises(SeraphimError):
        TaskResult(outcome=T.SUCCEEDED, verification=EMPTY)


def test_invariant_rejects_succeeded_status_without_result():
    task = _in_status(T.SUCCEEDED)
    forged = Task(
        id=task.id, goal=task.goal, mode=task.mode, steps=task.steps,
        updated_at=TS, status=T.SUCCEEDED, result=None,
    )
    with pytest.raises(SeraphimError):
        check_invariants(forged)


def test_invariant_rejects_succeeded_step_without_passing_report():
    with pytest.raises(SeraphimError):
        PlanStep(
            id=S1, title="t", verification=("x",), status=StepStatus.SUCCEEDED, report=FAIL
        )
    with pytest.raises(SeraphimError):
        PlanStep(id=S1, title="t", verification=("x",), status=StepStatus.SUCCEEDED)


def test_check_outcome_pass_requires_evidence():
    with pytest.raises(SeraphimError):
        CheckOutcome("file_exists", True)


def test_empty_verification_report_is_not_passed():
    assert not EMPTY.passed
    assert PASS.passed and not FAIL.passed


def test_plan_rejects_cycles_duplicates_unknown_deps_and_empty_criteria():
    with pytest.raises(SeraphimError) as cyc:
        create_task(
            "g", TaskMode.ASSIST,
            (_step(S1, depends=(S2,)), _step(S2, depends=(S1,))), at=TS,
        )
    assert cyc.value.code == ErrorCode.PLAN_VALIDATION_FAILED
    with pytest.raises(SeraphimError) as dup:
        create_task("g", TaskMode.ASSIST, (_step(S1), _step(S1)), at=TS)
    assert dup.value.code == ErrorCode.PLAN_VALIDATION_FAILED
    with pytest.raises(SeraphimError) as unknown:
        create_task("g", TaskMode.ASSIST, (_step(S1, depends=(generate_id("step"),)),), at=TS)
    assert unknown.value.code == ErrorCode.PLAN_VALIDATION_FAILED
    with pytest.raises(SeraphimError) as empty:
        PlanStep(id=S1, title="t", verification=())
    assert empty.value.code == ErrorCode.PLAN_VALIDATION_FAILED


def test_transition_timestamp_is_validated():
    with pytest.raises(ValueError):
        transition(_task(_step(S1)), Prepare(), at="not-a-time")


@pytest.mark.parametrize("risk", ["write", "external", "destructive"])
def test_observe_mode_refuses_state_changing_steps(risk):
    step = PlanStep(id=S1, title="step", verification=("file_exists",), risk_hint=risk)
    task = create_task("goal", TaskMode.OBSERVE, (step,), at=TS)
    ready = _run(task, Prepare(), Start())
    with pytest.raises(SeraphimError) as exc:
        transition(ready, StartStep(S1), at=TS)
    assert exc.value.code == ErrorCode.TASK_INVALID


def test_observe_mode_runs_read_only_steps():
    step = PlanStep(id=S1, title="step", verification=("file_exists",), risk_hint="read")
    task = create_task("goal", TaskMode.OBSERVE, (step,), at=TS)
    running = _run(task, Prepare(), Start(), StartStep(S1))
    assert running.step(S1).status is StepStatus.RUNNING


@pytest.mark.parametrize("risk", ["external", "destructive"])
@pytest.mark.parametrize("mode", [TaskMode.ASSIST, TaskMode.EXECUTE_WITH_APPROVAL, TaskMode.AUTONOMOUS_WITHIN_POLICY])
def test_high_risk_step_needs_approval_in_every_mode(mode, risk):
    step = PlanStep(id=S1, title="step", verification=("file_exists",), risk_hint=risk)
    task = create_task("goal", mode, (step,), at=TS)
    waiting = _run(task, Prepare(), Start(), StartStep(S1))
    assert waiting.status is T.NEEDS_APPROVAL
    assert waiting.pending_approval_step == S1
