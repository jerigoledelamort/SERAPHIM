"""S24 real SQLite durable intent/result and execution state contracts."""
import json

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.core.dispatch_store import DispatchStore
from seraphim.core.task_machine import StartStep
from seraphim.core.task_store import TaskRepository, ToolCallLedger
from seraphim.storage import MigrationRunner
from seraphim.wings import CallStatus, ToolResult
from seraphim.wings.calls import ToolError

from tests.core.test_orchestration import TS, _call, _running_task


def test_fresh_migration_and_state_round_trip(db):
    task, step = _running_task(db)
    store = DispatchStore(db)
    assert MigrationRunner(db).status().current_version == MigrationRunner(db).status().head_version
    assert MigrationRunner(db).run().applied == ()
    assert store.get_state(task) is None
    store.save_state(task, {"step_id": step, "messages": [], "turns": 2})
    assert DispatchStore(db).get_state(task)["turns"] == 2
    store.event(task, "ExecutorTurn", {"turn": 2})
    assert db.query_one("SELECT * FROM events WHERE type='ExecutorTurn'")
    TaskRepository(db).set_review(task, required=True, reason="review", at=TS)
    store.save_state(task, {"phase": "stopped"})
    assert store.get_state(task) == {"phase": "stopped"}
    assert TaskRepository(db).load(task).review_required


def test_atomic_intent_ledger_and_result(db):
    task, step = _running_task(db, "none")
    repo = TaskRepository(db)
    repo.save(repo.load(task), StartStep(step), event_type="StepStarted", at=TS)
    call = _call(task_id=task, step_id=step)
    store = DispatchStore(db)
    store.reserve(task, step, call, "internal", "provider-42")
    store.begin(call.call_id)
    assert len(ToolCallLedger(db).open_calls(task)) == 1
    row = store.calls(task)[0]
    assert json.loads(row["call_json"]) == call.to_dict()
    assert row["provider_call_id"] == "provider-42"
    result = ToolResult(call.call_id, call.tool_id, CallStatus.SUCCEEDED, 1, output={"ok": True})
    store.finish(call.call_id, result)
    assert ToolCallLedger(db).open_calls(task) == []
    assert json.loads(store.calls(task)[0]["result_json"]) == result.to_dict()
    with pytest.raises(SeraphimError):
        store.reserve(task, step, call, "internal")


def test_recovery_unknown_cannot_be_overwritten_by_late_result(db):
    task, step = _running_task(db, "none")
    repo = TaskRepository(db)
    repo.save(repo.load(task), StartStep(step), event_type="StepStarted", at=TS)
    store = DispatchStore(db)
    call = _call(task_id=task, step_id=step)
    store.reserve(task, step, call, "internal")
    store.begin(call.call_id)
    ToolCallLedger(db).mark_unknown(task)
    result = ToolResult(call.call_id, call.tool_id, CallStatus.SUCCEEDED, 1, output={})
    with pytest.raises(SeraphimError):
        store.finish(call.call_id, result)
    store.save_state(task, {"phase": "stopped"})
    assert store.calls(task)[0]["status"] == "UNKNOWN"
    assert store.calls(task)[0]["result_json"] is None


def test_single_open_operation_across_stores_and_unknown_blocks(db):
    task, step = _running_task(db, "none")
    repo = TaskRepository(db)
    repo.save(repo.load(task), StartStep(step), event_type="StepStarted", at=TS)
    call = _call(task_id=task, step_id=step)
    store = DispatchStore(db)
    store.reserve(task, step, call, "internal")
    with pytest.raises(SeraphimError):
        DispatchStore(db).reserve(task, step, _call(), "internal")
    store.begin(call.call_id)
    store.finish(call.call_id, ToolResult(call.call_id, call.tool_id, CallStatus.FAILED, 1,
                 error=ToolError("TOOL_TIMEOUT", "unknown")), unknown=True)
    assert store.calls(task)[0]["status"] == "UNKNOWN"
    assert repo.load(task).review_required
    with pytest.raises(SeraphimError):
        store.reserve(task, step, _call(), "internal")
