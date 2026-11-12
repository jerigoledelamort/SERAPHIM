from __future__ import annotations

import json

import pytest
from seraphim.aegis import PolicyEngine, PolicyRule, build_policy_set
from seraphim.compass.router import Candidate
from seraphim.core.execution_model import ExecutionLimits
from seraphim.core.executor import Executor
from seraphim.core.orchestration import StepOrchestrator
from seraphim.core.task_model import TaskStatus
from seraphim.model_layer.capabilities import ProviderCapabilities
from seraphim.model_layer.fake import FakeProvider, FakeTurn
from seraphim.model_layer.health import HealthStatus
from seraphim.storage import Database, MigrationRunner
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.fs_tools import register_fs_tools
from seraphim.wings.registry import ToolRegistry


def _runtime(tmp_path, turns, limits=None):
    root = tmp_path / "sandbox"
    root.mkdir()
    db = Database.open(tmp_path / "runtime", environ={})
    MigrationRunner(db).run()
    registry = ToolRegistry()
    register_fs_tools(registry, FsRoot(root))
    engine = PolicyEngine(build_policy_set((PolicyRule(
        rule_id="aegis.user.sandbox", source="user", outcome="ALLOW", tool_pattern="tool.fs.*"),)))
    provider = FakeProvider(capabilities=ProviderCapabilities(tool_calls=True), script=[FakeTurn(text=json.dumps({
        "goal": "write test file", "steps": [{"id": "write", "title": "write file",
            "verification": ["file_exists"], "expected_outputs": ["a.txt"], "risk_hint": "write"}]
    })), *turns])
    executor = Executor(db, registry, StepOrchestrator(db, registry, engine, actor="tester"),
        [Candidate("fake-model", provider, external=False, health=HealthStatus.ONLINE)], limits=limits)
    return executor, provider, root, db


def _call(name="tool.fs.write_file", arguments=None, call_id="external-call-1"):
    return {"id": call_id, "name": name, "arguments": arguments or {"path": "a.txt", "text": "hello"}}


def test_goal_to_durable_tool_result_and_tool_message(tmp_path):
    executor, provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()]), FakeTurn(text="done")])
    task_id = executor.create("write test file")
    outcome = executor.run(task_id)
    assert outcome.status == "VERIFYING"
    assert (root / "a.txt").read_text() == "hello"
    task = executor.tasks.load(task_id).task
    assert task.status is not TaskStatus.SUCCEEDED
    assert task.steps[0].attempts == 1
    assert provider.last_request.messages[-1].role == "tool"
    assert provider.last_request.messages[-2].tool_calls[0].id == "external-call-1"
    assert db.query("SELECT * FROM tool_calls WHERE task_id = ?", (task_id,))


def test_multiple_calls_start_attempt_once(tmp_path):
    executor, _, root, _ = _runtime(tmp_path, [FakeTurn(tool_calls=[
        _call(), _call(arguments={"path": "b.txt", "text": "two"}, call_id="second")]), FakeTurn(text="done")])
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "VERIFYING"
    assert executor.tasks.load(task_id).task.steps[0].attempts == 1
    assert (root / "b.txt").read_text() == "two"


def test_first_failure_stops_remaining_batch(tmp_path):
    executor, _, root, _ = _runtime(tmp_path, [FakeTurn(tool_calls=[
        _call("tool.fs.read_file", {"path": "missing.txt"}),
        _call(arguments={"path": "never.txt", "text": "no"}, call_id="second")])])
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "BLOCKED"
    assert not (root / "never.txt").exists()
    assert len(executor.store.get_state(task_id)["unexecuted_calls"]) == 1


@pytest.mark.parametrize("limits,turn", [
    (ExecutionLimits(max_calls_per_turn=1), FakeTurn(tool_calls=[_call(), _call(call_id="two")])),
    (ExecutionLimits(max_arguments_bytes=4), FakeTurn(tool_calls=[_call()])),
    (ExecutionLimits(max_output_bytes=16), FakeTurn(text="x" * 100)),
])
def test_invalid_or_oversized_batch_has_no_effect(tmp_path, limits, turn):
    executor, _, root, _ = _runtime(tmp_path, [turn], limits)
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "BLOCKED"
    assert not (root / "a.txt").exists()


def test_turn_budget_not_controlled_by_model(tmp_path):
    executor, _, root, _ = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()])], ExecutionLimits(max_turns=1))
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "BLOCKED"
    assert (root / "a.txt").exists()
    assert executor.store.get_state(task_id)["turns"] == 1


def test_approval_round_trip_returns_persisted_result_to_model(tmp_path):
    from seraphim.aegis import PolicySet
    from seraphim.core.approval import ApprovalService

    executor, provider, root, db = _runtime(tmp_path, [
        FakeTurn(tool_calls=[_call()]), FakeTurn(text="done")])
    executor.orchestrator._engine = PolicyEngine(PolicySet((
        PolicyRule(rule_id="aegis.global.confirm", source="global", outcome="ASK_USER",
                   waived_when_confirmed=True),
        PolicyRule(rule_id="aegis.user.allow", source="user", outcome="ALLOW"),
    )))
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "NEEDS_APPROVAL"
    state = executor.store.get_state(task_id)
    assert state["pending_call"]
    approval = ApprovalService(db).pending(task_id)[0]
    assert executor.approve(task_id, approval.id).status == "VERIFYING"
    assert (root / "a.txt").read_text() == "hello"
    assert provider.last_request.messages[-1].role == "tool"


def test_model_failure_blocks_without_tool_effect(tmp_path):
    executor, _, root, _ = _runtime(tmp_path, [FakeTurn(error_kind="timeout")])
    task_id = executor.create("write test file")
    assert executor.run(task_id).status == "BLOCKED"
    assert not (root / "a.txt").exists()
