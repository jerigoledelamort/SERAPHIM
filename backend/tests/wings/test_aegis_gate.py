# WINGS + AEGIS integration (S20). The real PolicyEngine decides; providers are fakes.
# Every test checks the provider was not called on refusal, the reason is explained,
# and the registry stays usable afterwards.

from __future__ import annotations

from typing import Any

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
from seraphim.wings import CallStatus, ToolCall, ToolManifest, ToolRegistry


def _manifest(
    tool_id: str = "tool.fs.read_file",
    *,
    side_effects: str = "read",
    risk: str = "low",
    source: str = "core",
    capabilities: tuple[str, ...] = ("filesystem.read",),
) -> ToolManifest:
    return ToolManifest(
        id=tool_id,
        description="Test tool.",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        capabilities=capabilities,
        risk=risk,
        side_effects=side_effects,
        permissions=("filesystem.read",),
        timeout_seconds=5,
        supports_cancellation=False,
        idempotency="idempotent",
        source=source,
        version="1.0",
    )


class _Provider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"text": "ok"}


def _call(tool_id: str = "tool.fs.read_file") -> ToolCall:
    return ToolCall(call_id=generate_id("call"), tool_id=tool_id, arguments={"path": "a.txt"})


def _registry(manifest: ToolManifest, policy_set: PolicySet) -> tuple[ToolRegistry, _Provider, Any]:
    registry = ToolRegistry()
    provider = _Provider()
    registry.register(manifest, provider)
    gate = make_gate(PolicyEngine(policy_set), actor="agent_main")
    return registry, provider, gate


def _allow(tool_pattern: str, side_effects: tuple[str, ...] = ("read",)) -> PolicyRule:
    return PolicyRule(
        rule_id=f"aegis.user.allow.{tool_pattern.replace('*', 'all').replace('.', '_')}",
        outcome="ALLOW",
        source="user",
        tool_pattern=tool_pattern,
        side_effects=side_effects,
    )


def test_limits_fail_closed_without_trusted_resource_resolver(tmp_path):
    rule = PolicyRule(rule_id="aegis.user.limited", outcome="ALLOW_WITH_LIMITS", source="user",
                      limits=PolicyLimits(allowed_roots=(str(tmp_path),)))
    registry, provider, gate = _registry(_manifest(), build_policy_set((rule,)))
    assert registry.call(_call(), policy=gate).status is CallStatus.REJECTED
    assert provider.calls == 0


def test_move_checks_both_policy_resources(tmp_path):
    from seraphim.wings.fs_paths import FsRoot
    from seraphim.wings.fs_tools import register_fs_tools

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("safe")
    registry = ToolRegistry()
    register_fs_tools(registry, FsRoot(tmp_path))
    engine = PolicyEngine(build_policy_set((PolicyRule(
        rule_id="aegis.user.limited", outcome="ALLOW_WITH_LIMITS", source="user",
        limits=PolicyLimits(allowed_roots=(str(allowed),))),)))
    call = ToolCall(generate_id("call"), "tool.fs.move_path", {"path": "allowed/a.txt", "to": "outside.txt"})
    result = registry.call(call, policy=make_gate(engine, actor="tester", registry=registry))
    assert result.status is CallStatus.REJECTED
    assert (allowed / "a.txt").read_text() == "safe"
    assert not (tmp_path / "outside.txt").exists()


class TestDenyByDefault:
    def test_unknown_tool_is_not_executed(self) -> None:
        registry, provider, gate = _registry(_manifest(), build_policy_set((_allow("tool.fs.*"),)))
        result = registry.call(_call("tool.shell.run"), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_NOT_FOUND
        assert provider.calls == 0

    def test_registered_tool_without_any_rule_is_denied_before_provider(self) -> None:
        registry, provider, gate = _registry(_manifest(), PolicySet())
        result = registry.call(_call(), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_PERMISSION_DENIED
        assert provider.calls == 0

    def test_refusal_explains_reason_without_internal_details(self) -> None:
        registry, _, gate = _registry(_manifest(), PolicySet())
        result = registry.call(_call(), policy=gate)
        assert result.error is not None
        assert result.error.safe_message == "No policy rule allows this action."
        assert "Traceback" not in result.error.safe_message

    def test_missing_policy_gate_rejects_every_call(self) -> None:
        registry, provider, _ = _registry(_manifest(), build_policy_set((_allow("tool.fs.*"),)))
        result = registry.call(_call())
        assert result.status is CallStatus.REJECTED
        assert provider.calls == 0


class TestSideEffects:
    def test_destructive_tool_needs_confirmation_and_is_not_executed(self) -> None:
        manifest = _manifest("tool.fs.delete_file", side_effects="destructive", risk="high")
        registry, provider, gate = _registry(manifest, build_policy_set((_allow("tool.fs.*", ("destructive",)),)))
        result = registry.call(_call("tool.fs.delete_file"), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and "confirmation" in result.error.safe_message
        assert provider.calls == 0

    def test_external_tool_needs_confirmation_and_is_not_executed(self) -> None:
        manifest = _manifest("tool.net.get", side_effects="external", risk="medium", capabilities=("network.http.get",))
        registry, provider, gate = _registry(manifest, build_policy_set((_allow("tool.net.*", ("external",)),)))
        result = registry.call(_call("tool.net.get"), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert provider.calls == 0

    def test_write_tool_without_explicit_allow_is_denied(self) -> None:
        manifest = _manifest("tool.fs.write_file", side_effects="write", risk="medium", capabilities=("filesystem.write",))
        registry, provider, gate = _registry(manifest, PolicySet())
        assert registry.call(_call("tool.fs.write_file"), policy=gate).status is CallStatus.REJECTED
        assert provider.calls == 0


class TestAllowed:
    def test_allowed_read_executes_once(self) -> None:
        registry, provider, gate = _registry(_manifest(), build_policy_set((_allow("tool.fs.*"),)))
        result = registry.call(_call(), policy=gate)
        assert result.status is CallStatus.SUCCEEDED
        assert provider.calls == 1

    def test_allow_with_limits_still_executes(self) -> None:
        rule = PolicyRule(
            rule_id="aegis.user.limited",
            outcome="ALLOW_WITH_LIMITS",
            source="user",
            tool_pattern="tool.fs.read_file",
            side_effects=("read",),
            limits=PolicyLimits(timeout_seconds=5),
        )
        registry, provider, gate = _registry(_manifest(), build_policy_set((rule,)))
        assert registry.call(_call(), policy=gate).status is CallStatus.SUCCEEDED
        assert provider.calls == 1


class TestRegistryStaysUsable:
    def test_refusal_does_not_break_later_allowed_call(self) -> None:
        registry, provider, deny_gate = _registry(_manifest(), PolicySet())
        assert registry.call(_call(), policy=deny_gate).status is CallStatus.REJECTED
        allow_gate = make_gate(PolicyEngine(build_policy_set((_allow("tool.fs.*"),))), actor="agent_main")
        assert registry.call(_call(), policy=allow_gate).status is CallStatus.SUCCEEDED
        assert provider.calls == 1

    def test_disabled_tool_is_refused_even_with_allow_rule(self) -> None:
        registry, provider, gate = _registry(_manifest(), build_policy_set((_allow("tool.fs.*"),)))
        registry.disable("tool.fs.read_file")
        result = registry.call(_call(), policy=gate)
        assert result.status is CallStatus.REJECTED
        assert provider.calls == 0


class TestGateFailureIsDeny:
    def test_gate_that_raises_becomes_refusal_not_crash(self) -> None:
        registry, provider, _ = _registry(_manifest(), build_policy_set((_allow("tool.fs.*"),)))

        def broken_gate(manifest: Any, call: Any) -> Any:
            raise RuntimeError("engine exploded")

        result = registry.call(_call(), policy=broken_gate)
        assert result.status is CallStatus.REJECTED
        assert provider.calls == 0

    def test_gate_for_malformed_manifest_denies(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow("tool.fs.*"),)))
        gate = make_gate(engine, actor="agent_main")
        decision = gate(object(), _call())
        assert decision.outcome == "DENY"
        assert decision.rule_id == "aegis.gate.evaluation_failed"
