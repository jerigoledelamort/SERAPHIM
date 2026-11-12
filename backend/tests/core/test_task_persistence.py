# CORE task persistence and resume (S17). Real SQLite in a temp root; "restart"
# means building a fresh Database handle and TaskService over the same file.

from __future__ import annotations

from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.core.task_machine import (
    Approve,
    FailStep,
    Pause,
    Prepare,
    Resume,
    Start,
    StartStep,
    SubmitStep,
    Verified,
    transition,
)
from seraphim.core.task_model import (
    CheckOutcome,
    PlanStep,
    StepStatus,
    TaskMode,
    TaskStatus,
    VerificationReport,
    create_task,
)
from seraphim.core.task_service import TaskService
from seraphim.core.task_store import TaskRepository, ToolCallLedger
from seraphim.storage import Database, MigrationRunner

TS = "2026-11-12T10:00:00.000Z"
S1 = generate_id("step")
S2 = generate_id("step")
PASS = VerificationReport("verifier.fixture", (CheckOutcome("file_exists", True, "evidence_1"),))
T = TaskStatus


def _db(root: Path) -> Database:
    db = Database.open(root, environ={})
    MigrationRunner(db).run()
    return db


def _step(sid: str, *, attempts: int = 1, approval: bool = False) -> PlanStep:
    return PlanStep(
        id=sid, title="s", verification=("file_exists",),
        max_attempts=attempts, requires_approval=approval,
    )


def _draft(*steps: PlanStep):
    return create_task("goal", TaskMode.EXECUTE_WITH_APPROVAL, steps or (_step(S1),), at=TS)


def _apply(task, *events):
    for event in events:
        task = transition(task, event, at=TS)
    return task


@pytest.fixture
def root(test_root: Path) -> Path:
    return test_root


def _restart(root: Path) -> TaskService:
    """Simulate a process restart: brand-new handle and service over the same file."""
    return TaskService(_db(root))


def _seed(root: Path, draft, *events) -> str:
    """Insert a DRAFT task, then replay *events* through the repository (the real write path)."""
    repo = TaskRepository(_db(root))
    record = repo.insert(draft)
    for event in events:
        record = repo.save(record, event, event_type="Seed", at=TS)
    return draft.id


class TestRoundTrip:
    def test_created_task_restores_identical_state_after_restart(self, root: Path) -> None:
        draft = _draft(_step(S1), _step(S2, approval=True))
        task_id = _seed(root, draft)
        assert _restart(root).show(task_id).task == draft

    def test_plan_is_stored_once_and_state_changes_do_not_rewrite_it(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        db = _db(root)
        before = db.scalar("SELECT plan_json FROM tasks WHERE id = ?", (task_id,))
        repo = TaskRepository(db)
        ready = repo.save(repo.load(task_id), Prepare(), event_type="TaskPrepared", at=TS)
        repo.save(ready, Start(), event_type="TaskStarted", at=TS)
        assert db.scalar("SELECT plan_json FROM tasks WHERE id = ?", (task_id,)) == before

    def test_checkpoints_and_events_are_written_per_change(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        db = _db(root)
        repo = TaskRepository(db)
        repo.save(repo.load(task_id), Prepare(), event_type="TaskPrepared", at=TS)
        assert db.scalar("SELECT COUNT(*) FROM checkpoints WHERE task_id = ?", (task_id,)) == 2
        types = [r["type"] for r in db.query(
            "SELECT type FROM events WHERE task_id = ? ORDER BY rowid", (task_id,))]
        assert types == ["TaskCreated", "TaskPrepared"]

    def test_plan_and_outputs_are_not_a_transcript(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        db = _db(root)
        for table in ("tasks", "task_steps", "checkpoints", "events"):
            cols = [c["name"] for c in db.query(f"PRAGMA table_info({table})")]
            assert "transcript" not in cols and "messages" not in cols
        assert db.scalar("SELECT COUNT(*) FROM tasks WHERE id = ?", (task_id,)) == 1


class TestPauseResumeCancel:
    def test_pause_then_restart_then_resume_continues_the_same_step(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        TaskService(_db(root)).pause(task_id)
        service = _restart(root)
        assert service.show(task_id).task.status is T.PAUSED
        resumed = service.resume(task_id).task
        assert resumed.status is T.RUNNING
        assert resumed.step(S1).attempts == 1

    def test_repeated_resume_does_not_duplicate_work(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        service = TaskService(_db(root))
        service.pause(task_id)
        service.resume(task_id)
        with pytest.raises(SeraphimError) as exc:
            service.resume(task_id)
        assert exc.value.code == ErrorCode.TASK_INVALID
        final = service.show(task_id).task
        assert final.status is T.RUNNING
        assert final.step(S1).attempts == 1

    def test_resume_of_running_task_is_rejected_without_writing(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        service = TaskService(_db(root))
        revision = service.show(task_id).revision
        with pytest.raises(SeraphimError):
            service.resume(task_id)
        assert service.show(task_id).revision == revision

    def test_pause_on_terminal_task_is_rejected(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        service = TaskService(_db(root))
        service.cancel(task_id, "user stopped")
        with pytest.raises(SeraphimError):
            service.pause(task_id)
        assert service.show(task_id).task.status is T.CANCELLED

    def test_cancel_survives_restart_with_reason(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        TaskService(_db(root)).cancel(task_id, "user stopped")
        restored = _restart(root).show(task_id).task
        assert restored.status is T.CANCELLED
        assert restored.result is not None and restored.result.reason == "user stopped"

    def test_list_filters_by_status(self, root: Path) -> None:
        running_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        _seed(root, _draft(_step(S1)))
        service = _restart(root)
        assert {r.task.id for r in service.list(status=T.RUNNING)} == {running_id}
        assert len(service.list()) == 2


class TestConflicts:
    def test_stale_writer_gets_revision_conflict_and_nothing_is_written(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare())
        repo = TaskRepository(_db(root))
        stale = repo.load(task_id)
        repo.save(stale, Start(), event_type="A", at=TS)
        with pytest.raises(SeraphimError) as exc:
            repo.save(stale, Start(), event_type="B", at=TS)
        assert exc.value.code == ErrorCode.TASK_REVISION_CONFLICT
        assert repo.load(task_id).task.status is T.RUNNING
        assert repo.load(task_id).revision == 2

    def test_conflicting_pause_and_cancel_only_one_wins(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        repo = TaskRepository(_db(root))
        first = repo.load(task_id)
        second = repo.load(task_id)
        repo.save(first, Pause(), event_type="P", at=TS)
        with pytest.raises(SeraphimError) as exc:
            repo.save(second, Pause(), event_type="C", at=TS)
        assert exc.value.code == ErrorCode.TASK_REVISION_CONFLICT
        assert repo.load(task_id).task.status is T.PAUSED

    def test_illegal_transition_never_reaches_the_database(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        service = TaskService(_db(root))
        revision = service.show(task_id).revision
        with pytest.raises(SeraphimError):
            service.pause(task_id)
        assert service.show(task_id).revision == revision


class TestRestartInEachState:
    @pytest.mark.parametrize(
        ("draft", "events", "expected"),
        [
            (_draft(_step(S1)), (), T.DRAFT),
            (_draft(_step(S1)), (Prepare(),), T.READY),
            (_draft(_step(S1)), (Prepare(), Start()), T.RUNNING),
            (_draft(_step(S1)), (Prepare(), Start(), StartStep(S1), SubmitStep(S1)), T.VERIFYING),
            (_draft(_step(S1, approval=True)), (Prepare(), Start(), StartStep(S1)), T.NEEDS_APPROVAL),
            (_draft(_step(S1, attempts=2)), (Prepare(), Start(), StartStep(S1), FailStep(S1)), T.RETRYING),
            (_draft(_step(S1)), (Prepare(), Start(), Pause()), T.PAUSED),
        ],
        ids=["DRAFT", "READY", "RUNNING", "VERIFYING", "NEEDS_APPROVAL", "RETRYING", "PAUSED"],
    )
    def test_state_is_restored_exactly(self, root: Path, draft, events, expected) -> None:
        task_id = _seed(root, draft, *events)
        restored = _restart(root).show(task_id).task
        assert restored.status is expected
        assert restored == _apply(draft, *events)


class TestRecovery:
    def test_paused_task_is_left_paused_and_not_flagged(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), Pause())
        report = _restart(root).recover()
        assert report.paused == (task_id,)
        assert report.flagged_for_review == ()
        assert _restart(root).show(task_id).review_required is False

    @pytest.mark.parametrize(
        ("draft", "events"),
        [
            (_draft(_step(S1)), (Prepare(), Start(), StartStep(S1))),
            (_draft(_step(S1)), (Prepare(), Start(), StartStep(S1), SubmitStep(S1))),
            (_draft(_step(S1, approval=True)), (Prepare(), Start(), StartStep(S1))),
        ],
        ids=["RUNNING", "VERIFYING", "NEEDS_APPROVAL"],
    )
    def test_unfinished_active_task_is_routed_to_review_not_continued(
        self, root: Path, draft, events
    ) -> None:
        task_id = _seed(root, draft, *events)
        status_before = _restart(root).show(task_id).task.status
        report = _restart(root).recover()
        assert report.flagged_for_review == (task_id,)
        record = _restart(root).show(task_id)
        assert record.review_required is True
        assert record.task.status is status_before

    def test_review_task_refuses_resume_and_advance_until_cleared(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), Pause())
        service = _restart(root)
        service.tasks.set_review(task_id, required=True, reason="manual", at=TS)
        with pytest.raises(SeraphimError) as exc:
            _restart(root).resume(task_id)
        assert exc.value.code == ErrorCode.TASK_REVIEW_REQUIRED
        service.review_clear(task_id, note="checked")
        assert _restart(root).resume(task_id).task.status is T.RUNNING

    def test_review_flag_blocks_direct_repository_writes(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start())
        repo = TaskRepository(_db(root))
        repo.set_review(task_id, required=True, reason="manual", at=TS)
        record = repo.load(task_id)
        with pytest.raises(SeraphimError) as exc:
            repo.save(record, Pause(), event_type="X", at=TS)
        assert exc.value.code == ErrorCode.TASK_REVIEW_REQUIRED

    def test_illegal_event_is_rejected_by_save_and_nothing_is_written(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        repo = TaskRepository(_db(root))
        record = repo.load(task_id)
        with pytest.raises(SeraphimError) as exc:
            repo.save(record, Resume(), event_type="X", at=TS)
        assert exc.value.code == ErrorCode.TASK_INVALID
        assert repo.load(task_id).revision == record.revision
        assert repo.load(task_id).task.status is T.DRAFT

    def test_insert_rejects_non_draft_task(self, root: Path) -> None:
        task = _apply(_draft(_step(S1)), Prepare(), Start())
        with pytest.raises(SeraphimError) as exc:
            TaskRepository(_db(root)).insert(task)
        assert exc.value.code == ErrorCode.TASK_INVALID

    def test_cancel_is_allowed_while_task_is_under_review(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        _restart(root).recover()
        cancelled = _restart(root).cancel(task_id, "operator closed it").task
        assert cancelled.status is T.CANCELLED

    def test_repeated_recovery_is_idempotent_for_state_and_calls(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        _restart(root).recover()
        before = _restart(root).show(task_id)
        _restart(root).recover()
        after = _restart(root).show(task_id)
        assert after.task == before.task
        assert after.review_required is True


class TestToolCallsAndCrash:
    def test_open_call_after_crash_is_unknown_and_task_needs_review(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ToolCallLedger(_db(root)).begin(task_id, S1, "write_file", "key-1")
        report = _restart(root).recover()
        assert report.flagged_for_review == (task_id,)
        status = _db(root).scalar("SELECT status FROM tool_calls WHERE idempotency_key = ?", ("key-1",))
        assert status == "UNKNOWN"
        assert _restart(root).show(task_id).review_required is True

    def test_repeat_recovery_does_not_reissue_or_duplicate_the_call(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ToolCallLedger(_db(root)).begin(task_id, S1, "write_file", "key-2")
        _restart(root).recover()
        _restart(root).recover()
        db = _db(root)
        assert db.scalar("SELECT COUNT(*) FROM tool_calls WHERE task_id = ?", (task_id,)) == 1
        assert db.scalar("SELECT status FROM tool_calls WHERE task_id = ?", (task_id,)) == "UNKNOWN"

    def test_same_idempotency_key_cannot_be_recorded_twice(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ledger = ToolCallLedger(_db(root))
        ledger.begin(task_id, S1, "write_file", "key-3")
        with pytest.raises(SeraphimError):
            ledger.begin(task_id, S1, "write_file", "key-3")

    def test_completed_call_is_not_marked_unknown(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ledger = ToolCallLedger(_db(root))
        call_id = ledger.begin(task_id, S1, "write_file", "key-4")
        ledger.finish(call_id, "COMPLETED", outcome_ref="artifact_ref")
        assert _restart(root).recover().flagged_for_review == (task_id,)
        assert _restart(root).show(task_id).review_required is True
        assert _db(root).scalar("SELECT status FROM tool_calls WHERE id = ?", (call_id,)) == "COMPLETED"

    def test_finish_twice_is_rejected(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ledger = ToolCallLedger(_db(root))
        call_id = ledger.begin(task_id, S1, "write_file", "key-5")
        ledger.finish(call_id, "COMPLETED")
        with pytest.raises(SeraphimError):
            ledger.finish(call_id, "FAILED")

    def test_tool_call_cannot_begin_while_task_is_under_review(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        TaskRepository(_db(root)).set_review(task_id, required=True, reason="manual", at=TS)
        with pytest.raises(SeraphimError) as exc:
            ToolCallLedger(_db(root)).begin(task_id, S1, "write_file", "key-review")
        assert exc.value.code == ErrorCode.TASK_REVIEW_REQUIRED
        assert _db(root).scalar("SELECT COUNT(*) FROM tool_calls WHERE task_id = ?", (task_id,)) == 0

    def test_tool_call_cannot_begin_when_task_is_not_running(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), Pause())
        with pytest.raises(SeraphimError) as exc:
            ToolCallLedger(_db(root)).begin(task_id, S1, "write_file", "key-paused")
        assert exc.value.code == ErrorCode.TASK_INVALID

    def test_open_call_on_task_already_under_review_is_marked_unknown(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)), Prepare(), Start(), StartStep(S1))
        ToolCallLedger(_db(root)).begin(task_id, S1, "write_file", "key-order")
        TaskRepository(_db(root)).set_review(task_id, required=True, reason="manual", at=TS)
        _restart(root).recover()
        assert _db(root).scalar(
            "SELECT status FROM tool_calls WHERE idempotency_key = ?", ("key-order",)
        ) == "UNKNOWN"


class TestStepsSurviveRestart:
    def test_step_report_and_attempts_survive_restart(self, root: Path) -> None:
        draft = _draft(_step(S1, attempts=2))
        events = (Prepare(), Start(), StartStep(S1), SubmitStep(S1), Verified(S1, PASS))
        task_id = _seed(root, draft, *events)
        restored = _restart(root).show(task_id).task
        assert restored.step(S1).status is StepStatus.SUCCEEDED
        assert restored.step(S1).attempts == 1
        assert restored.step(S1).report == PASS

    def test_approval_binding_survives_restart(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1, approval=True)), Prepare(), Start(), StartStep(S1))
        assert _restart(root).show(task_id).task.pending_approval_step == S1
        approved = transition(_restart(root).show(task_id).task, Approve(S1), at=TS)
        assert approved.status is T.RUNNING
        assert approved.approved_step_id == S1


class TestPlanSchemaVersion:
    def test_stored_plan_carries_schema_version(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        raw = _db(root).scalar("SELECT plan_json FROM tasks WHERE id = ?", (task_id,))
        assert '"schema_version":1' in raw

    def test_unknown_plan_schema_version_is_rejected_on_load(self, root: Path) -> None:
        task_id = _seed(root, _draft(_step(S1)))
        db = _db(root)
        db.execute(
            "UPDATE tasks SET plan_json = REPLACE(plan_json, '\"schema_version\":1', '\"schema_version\":9') WHERE id = ?",
            (task_id,),
        )
        with pytest.raises(SeraphimError) as exc:
            TaskRepository(db).load(task_id)
        assert exc.value.code == ErrorCode.TASK_INVALID
