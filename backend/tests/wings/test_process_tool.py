# WINGS process tool behind the AEGIS gate (S22). Offline: runs only the current interpreter.

from __future__ import annotations

import os
import sys
from pathlib import Path

from seraphim.aegis import (
    PolicyEngine,
    PolicyLimits,
    PolicyRule,
    PolicySet,
    build_policy_set,
    make_gate,
)
from seraphim.contracts.errors import ErrorCode
from seraphim.contracts.ids import generate_id
from seraphim.wings import CallStatus, ToolCall, ToolRegistry
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.process_tools import PROCESS_MANIFEST, ProcessToolProvider

PY_ENV_PATH = os.path.dirname(sys.executable)


def _call(**arguments: object) -> ToolCall:
    return ToolCall(call_id=generate_id("call"), tool_id="tool.process.run", arguments=dict(arguments))


def _registry(sandbox: FsRoot) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(PROCESS_MANIFEST, ProcessToolProvider(sandbox, allowed_executables=("python",)))
    return registry


def _allow_process_gate() -> object:
    rule = PolicyRule(
        rule_id="aegis.user.allow_process_run",
        outcome="ALLOW",
        source="user",
        tool_pattern="tool.process.run",
        side_effects=("external",),
    )
    return make_gate(PolicyEngine(build_policy_set((rule,))), actor="test")


class TestProcessToolGate:
    def test_refused_without_allow_rule(self, tmp_path: Path) -> None:
        registry = _registry(FsRoot(tmp_path))
        marker = tmp_path / "ran.txt"
        result = registry.call(
            _call(executable="python", argv=["-c", f"open({str(marker)!r},'w').write('x')"]),
            policy=make_gate(PolicyEngine(PolicySet()), actor="test"),
        )
        assert result.status is CallStatus.REJECTED
        assert not marker.exists()

    def test_user_allow_alone_does_not_skip_external_confirmation(self, tmp_path: Path) -> None:
        registry = _registry(FsRoot(tmp_path))
        marker = tmp_path / "ran.txt"
        result = registry.call(
            _call(executable="python", argv=["-c", f"open({str(marker)!r},'w').write('x')"]),
            policy=_allow_process_gate(),
        )
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and "confirmation" in result.error.safe_message
        assert not marker.exists()

    def test_user_limits_rule_cannot_override_global_confirmation(self, tmp_path: Path) -> None:
        registry = _registry(FsRoot(tmp_path))
        confirmed = PolicyRule(
            rule_id="aegis.user.limited_process",
            outcome="ALLOW_WITH_LIMITS",
            source="user",
            tool_pattern="tool.process.run",
            side_effects=("external",),
            limits=PolicyLimits(timeout_seconds=30),
        )
        gate = make_gate(PolicyEngine(build_policy_set((confirmed,))), actor="test")
        result = registry.call(_call(executable="python", argv=["-c", "pass"]), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and "confirmation" in result.error.safe_message

    def test_argument_schema_rejects_unknown_fields(self, tmp_path: Path) -> None:
        registry = _registry(FsRoot(tmp_path))
        result = registry.call(_call(executable="python", shell="cmd /c dir"), policy=_allow_process_gate())
        assert result.status is CallStatus.REJECTED

    def test_executable_outside_allowlist_is_not_run(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(PROCESS_MANIFEST, ProcessToolProvider(FsRoot(tmp_path), allowed_executables=()))
        confirmed = PolicyRule(
            rule_id="aegis.user.confirmed_process",
            outcome="ALLOW",
            source="user",
            tool_pattern="tool.process.run",
            side_effects=("external",),
        )
        gate = make_gate(PolicyEngine(build_policy_set((confirmed,))), actor="test", confirmed=lambda call: True)
        result = registry.call(_call(executable="python", argv=["-c", "pass"]), policy=gate)
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.VALIDATION_FAILED

    def test_manifest_requires_process_permission(self) -> None:
        assert PROCESS_MANIFEST.side_effects == "external"
        assert PROCESS_MANIFEST.permissions == ("process.run",)
