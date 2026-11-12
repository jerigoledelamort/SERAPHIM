from __future__ import annotations

import os
import sys

from seraphim.aegis import PolicyEngine, PolicyRule, build_policy_set
from seraphim.core.approval import ApprovalService
from seraphim.core.evidence import CheckSpec
from seraphim.core.verification import VerificationEngine
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.process_tools import PROCESS_MANIFEST, ProcessToolProvider

from tests.core.test_executor import _call, _runtime


def test_actual_process_output_is_persisted_evidence(tmp_path, monkeypatch):
    from seraphim.model_layer.fake import FakeTurn

    monkeypatch.setenv("PATH", os.path.dirname(sys.executable))
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call(
        "tool.process.run", {"executable": "python", "argv": ["-c", "print('evidence-ok')"]}
    )]), FakeTurn(text="done")])
    executor.registry.register(PROCESS_MANIFEST, ProcessToolProvider(
        FsRoot(root), allowed_executables=("python",)))
    executor.orchestrator._engine = PolicyEngine(build_policy_set((PolicyRule(
        rule_id="aegis.user.process", source="user", outcome="ALLOW", tool_pattern="tool.process.run",
    ),)))
    task_id = executor.create("run local evidence test")
    assert executor.run(task_id).status == "NEEDS_APPROVAL"
    approval = ApprovalService(db).pending(task_id)[0]
    assert executor.approve(task_id, approval.id).status == "VERIFYING"
    call = executor.store.calls(task_id)[0]
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    report = engine.check(task_id, "process", [
        CheckSpec("command_exit", expected="0", call_id=call["call_id"]),
        CheckSpec("test_output", expected="evidence-ok", call_id=call["call_id"]),
    ])
    assert report.passed
    assert all(check.source == "ledger:" + call["call_id"] for check in report.checks)
    assert not engine.check(task_id, "process", [
        CheckSpec("test_output", expected="not-in-output", call_id=call["call_id"]),
    ]).passed
