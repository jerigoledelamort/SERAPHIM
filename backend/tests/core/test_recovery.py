from __future__ import annotations

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.core.anti_loop import fingerprint, inspect
from seraphim.core.recovery import RecoveryEngine
from seraphim.model_layer.fake import FakeTurn

from tests.core.test_executor import _call, _runtime


def test_canonical_actions_ignore_argument_order_and_detect_repetition():
    action = fingerprint("tool", "1", {"a": 1, "b": 2})
    assert action == fingerprint("tool", "1", {"b": 2, "a": 1})
    assert inspect([action, action], action)
    assert not inspect([action], "new")
    assert inspect(["a", "b", "a", "b", "a"], "b")


def test_executor_blocks_unchanged_repeated_calls_after_initial_progress(tmp_path):
    executor, _provider, root, _db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call(call_id=str(i))]) for i in range(4)])
    task_id = executor.create("bounded repeated write")
    assert executor.run(task_id).status == "BLOCKED"
    assert len(executor.store.calls(task_id)) == 3
    assert executor.tasks.load(task_id).review_required
    assert (root / "a.txt").read_text() == "hello"


def test_competing_execution_owner_is_not_stolen(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()])])
    task_id = executor.create("exclusive execution")
    executor.store.claim(task_id, "existing-owner")
    with pytest.raises(SeraphimError):
        executor.run(task_id)
    assert not (root / "a.txt").exists()
    checkpoint = RecoveryEngine(db).inspect(task_id)
    assert checkpoint["decision"] == "owned_inspection_only"
    assert db.query_one("SELECT owner FROM execution_owners WHERE task_id=?", (task_id,))["owner"] == "existing-owner"


def test_approval_competitor_cannot_consume_or_execute(tmp_path):
    from seraphim.aegis import PolicyEngine, PolicyRule, PolicySet
    from seraphim.core.approval import ApprovalService

    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()])])
    executor.orchestrator._engine = PolicyEngine(PolicySet((
        PolicyRule(rule_id="aegis.global.confirm", source="global", outcome="ASK_USER", waived_when_confirmed=True),
        PolicyRule(rule_id="aegis.user.allow", source="user", outcome="ALLOW"),
    )))
    task_id = executor.create("approval ownership")
    assert executor.run(task_id).status == "NEEDS_APPROVAL"
    approval = ApprovalService(db).pending(task_id)[0]
    executor.store.claim(task_id, "competitor", approval=True)
    with pytest.raises(SeraphimError):
        executor.approve(task_id, approval.id)
    assert ApprovalService(db).pending(task_id)[0].id == approval.id
    assert not (root / "a.txt").exists()


def test_active_inspection_does_not_rewrite_started_ledger(tmp_path):
    from seraphim.contracts.ids import generate_id
    from seraphim.contracts.timestamps import now_utc
    from seraphim.core.task_machine import StartStep
    from seraphim.wings.calls import CallStatus, ToolCall, ToolResult

    executor, _provider, _root, db = _runtime(tmp_path, [])
    task_id = executor.create("active inspection")
    step_id = executor.tasks.load(task_id).task.steps[0].id
    executor.tasks.save(executor.tasks.load(task_id), StartStep(step_id), event_type="StepStarted", at=now_utc())
    executor.store.claim(task_id, "active")
    call = ToolCall(generate_id("call"), "tool.fs.write_file", {"path": "a.txt", "text": "hello"}, task_id, step_id)
    executor.store.reserve(task_id, step_id, call, "internal", owner="active")
    executor.store.begin(call.call_id, owner="active")
    assert RecoveryEngine(db).inspect(task_id)["decision"] == "owned_inspection_only"
    assert executor.store.calls(task_id)[0]["status"] == "STARTED"
    executor.store.finish(call.call_id, ToolResult(call.call_id, call.tool_id, CallStatus.SUCCEEDED, 0, output={}))
    assert executor.store.calls(task_id)[0]["status"] == "COMPLETED"
    executor.store.release(task_id, "active")


def test_interrupted_approval_accounting_never_restores_time(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [])
    task_id = executor.create("interrupted approval")
    state = executor.store.get_state(task_id)
    state["approval_accounting_pending"] = True
    executor.store.save_state(task_id, state)
    assert RecoveryEngine(db).inspect(task_id)["decision"] == "review"
    assert executor.run(task_id).status == "BLOCKED"
    assert executor.tasks.load(task_id).review_required
    assert not (root / "a.txt").exists()


def test_direct_orchestrator_cannot_approve_executor_task(tmp_path):
    from seraphim.aegis import PolicyEngine, PolicyRule, PolicySet
    from seraphim.core.approval import ApprovalService
    from seraphim.wings.calls import ToolCall

    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()])])
    executor.orchestrator._engine = PolicyEngine(PolicySet((
        PolicyRule(rule_id="aegis.global.confirm", source="global", outcome="ASK_USER", waived_when_confirmed=True),
        PolicyRule(rule_id="aegis.user.allow", source="user", outcome="ALLOW"),
    )))
    task_id = executor.create("direct approval must fail")
    assert executor.run(task_id).status == "NEEDS_APPROVAL"
    approval = ApprovalService(db).pending(task_id)[0]
    call = ToolCall(**executor.store.get_state(task_id)["pending_call"])
    with pytest.raises(SeraphimError):
        executor.orchestrator.approve(task_id, call.step_id, approval.id, call)
    assert ApprovalService(db).pending(task_id)[0].id == approval.id
    assert not (root / "a.txt").exists()


def test_persisted_limits_cannot_be_enlarged(tmp_path):
    from seraphim.core.execution_model import ExecutionLimits

    executor, _provider, root, _db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()])], ExecutionLimits(max_turns=1))
    task_id = executor.create("persistent budget")
    executor.limits = ExecutionLimits(max_turns=100)
    assert executor.run(task_id).status == "BLOCKED"
    assert executor.store.get_state(task_id)["turns"] == 1
    assert (root / "a.txt").exists()


@pytest.mark.parametrize("status", ["STARTED", "UNKNOWN"])
def test_orphan_ledger_overrides_ready_cursor(tmp_path, status):
    from seraphim.contracts.ids import generate_id
    from seraphim.contracts.timestamps import now_utc

    executor, _provider, _root, db = _runtime(tmp_path, [])
    task_id = executor.create("orphan ledger")
    step_id = executor.tasks.load(task_id).task.steps[0].id
    db.execute("INSERT INTO tool_calls(id,task_id,step_id,operation,idempotency_key,status,started_at) VALUES(?,?,?,?,?,?,?)",
               (generate_id("call"), task_id, step_id, "legacy.operation", "legacy", status, now_utc()))
    assert RecoveryEngine(db).inspect(task_id)["decision"] == "review"
    assert executor.tasks.load(task_id).review_required


def test_result_before_verification_only_requests_verification(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()]), FakeTurn(text="done")])
    task_id = executor.create("verify after restart")
    executor.run(task_id)
    recovery = RecoveryEngine(db)
    assert recovery.inspect(task_id)["decision"] == "verification_only"
    assert recovery.inspect(task_id)["decision"] == "verification_only"
    assert len(executor.store.calls(task_id)) == 1
    assert (root / "a.txt").read_text() == "hello"
    assert len(db.query("SELECT * FROM recovery_checkpoints WHERE task_id=?", (task_id,))) == 2
