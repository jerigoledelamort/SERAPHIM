# WINGS registry and tool contract (S19). Offline: fake providers only.

from __future__ import annotations

from typing import Any

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.wings import CallStatus, ToolCall, ToolManifest, ToolRegistry


def _manifest(
    tool_id: str = "tool.fs.read_file",
    *,
    capabilities: tuple[str, ...] = ("filesystem.read",),
    source: str = "core",
    input_schema: dict[str, Any] | None = None,
    timeout: int = 15,
    version: str = "1.0",
) -> ToolManifest:
    return ToolManifest(
        id=tool_id,
        description="Read a file inside an allowed root.",
        input_schema=input_schema
        if input_schema is not None
        else {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        capabilities=capabilities,
        risk="low",
        side_effects="read",
        permissions=("filesystem.read",),
        timeout_seconds=timeout,
        supports_cancellation=True,
        idempotency="idempotent",
        source=source,
        version=version,
    )


class _Provider:
    def __init__(self, output: Any = None, error: BaseException | None = None) -> None:
        self.output = {"text": "hi"} if output is None else output
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.output


def _call(tool_id: str = "tool.fs.read_file", **arguments: Any) -> ToolCall:
    return ToolCall(call_id=generate_id("call"), tool_id=tool_id, arguments=arguments or {"path": "a.txt"})


class TestManifestValidation:
    def test_valid_manifest_round_trips_to_dict(self) -> None:
        data = _manifest().to_dict()
        assert data["id"] == "tool.fs.read_file"
        assert data["capabilities"] == ["filesystem.read"]
        assert data["version"] == "1.0"

    @pytest.mark.parametrize(
        "tool_id",
        ["fs.read_file", "tool", "tool.", "other.read"],
        ids=["no-namespace", "bare", "empty-name", "wrong-namespace"],
    )
    def test_id_must_be_namespaced(self, tool_id: str) -> None:
        with pytest.raises(SeraphimError) as exc:
            _manifest(tool_id)
        assert exc.value.code == ErrorCode.TOOL_SCHEMA_INVALID

    @pytest.mark.parametrize(
        "schema",
        [
            "not a dict",
            {},
            {"type": "function"},
            {"type": "object", "properties": ["path"]},
        ],
        ids=["string", "no-type", "unknown-type", "properties-not-object"],
    )
    def test_invalid_input_schema_is_rejected(self, schema: Any) -> None:
        with pytest.raises(SeraphimError) as exc:
            _manifest(input_schema=schema)
        assert exc.value.code == ErrorCode.TOOL_SCHEMA_INVALID

    def test_timeout_bounds_are_enforced(self) -> None:
        for value in (0, 601, True):
            with pytest.raises(SeraphimError):
                _manifest(timeout=value)

    def test_version_must_be_dotted_integers(self) -> None:
        for value in ("", "v1", "1.x"):
            with pytest.raises(SeraphimError):
                _manifest(version=value)

    def test_unknown_source_or_risk_is_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            _manifest(source="random")
        bad = _manifest()
        with pytest.raises(SeraphimError):
            ToolManifest(**(bad.to_dict() | {"risk": "extreme", "tags": ()}))

    def test_duplicate_capability_in_one_manifest_is_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            _manifest(capabilities=("filesystem.read", "filesystem.read"))


class TestDuplicateIds:
    def test_second_registration_of_same_id_is_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider())
        with pytest.raises(SeraphimError) as exc:
            registry.register(_manifest(), _Provider())
        assert exc.value.code == ErrorCode.REGISTRY_CONFLICT

    def test_rejected_duplicate_does_not_replace_original_provider(self) -> None:
        registry = ToolRegistry()
        original = _Provider()
        registry.register(_manifest(), original)
        with pytest.raises(SeraphimError):
            registry.register(_manifest(), _Provider(output={"text": "other"}))
        registry.call(_call())
        assert len(original.calls) == 1


class TestCapabilityConflict:
    def test_same_capability_from_different_sources_is_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest("tool.fs.read_file", source="core"), _Provider())
        with pytest.raises(SeraphimError) as exc:
            registry.register(
                _manifest("tool.mcp.read_file", source="mcp", capabilities=("filesystem.read",)),
                _Provider(),
            )
        assert exc.value.code == ErrorCode.REGISTRY_CONFLICT
        assert "filesystem.read" in exc.value.safe_message

    def test_same_capability_from_same_source_is_allowed(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest("tool.fs.read_file"), _Provider())
        registry.register(_manifest("tool.fs.read_text"), _Provider())
        assert [m.id for m in registry.discover()] == ["tool.fs.read_file", "tool.fs.read_text"]

    def test_different_capabilities_from_different_sources_are_allowed(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest("tool.fs.read_file"), _Provider())
        registry.register(
            _manifest("tool.mcp.search", source="mcp", capabilities=("network.search",)),
            _Provider(),
        )
        assert len(registry.discover()) == 2


class TestEnableDisable:
    def test_disabled_tool_is_not_executed(self) -> None:
        provider = _Provider()
        registry = ToolRegistry()
        registry.register(_manifest(), provider, enabled=False)
        result = registry.call(_call())
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_PERMISSION_DENIED
        assert provider.calls == []

    def test_disable_then_enable_controls_execution(self) -> None:
        provider = _Provider()
        registry = ToolRegistry()
        registry.register(_manifest(), provider)
        registry.disable("tool.fs.read_file")
        assert registry.call(_call()).status is CallStatus.REJECTED
        registry.enable("tool.fs.read_file")
        assert registry.call(_call()).status is CallStatus.SUCCEEDED
        assert len(provider.calls) == 1

    def test_disabled_tool_is_hidden_from_discovery_by_default(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider(), enabled=False)
        assert registry.discover() == []
        assert [m.id for m in registry.discover(include_disabled=True)] == ["tool.fs.read_file"]
        assert registry.describe("tool.fs.read_file")["enabled"] is False

    def test_enable_unknown_tool_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            ToolRegistry().enable("tool.fs.ghost")
        assert exc.value.code == ErrorCode.TOOL_NOT_FOUND


class TestUnknownTool:
    def test_unknown_tool_is_not_executed_and_returns_structured_error(self) -> None:
        result = ToolRegistry().call(_call("tool.fs.ghost"))
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_NOT_FOUND
        assert result.output is None

    def test_unregistered_tool_cannot_be_described(self) -> None:
        with pytest.raises(SeraphimError):
            ToolRegistry().describe("tool.fs.ghost")


class TestArgumentsAndResults:
    def test_missing_required_argument_is_rejected_before_provider(self) -> None:
        provider = _Provider()
        registry = ToolRegistry()
        registry.register(_manifest(), provider)
        result = registry.call(
            ToolCall(call_id=generate_id("call"), tool_id="tool.fs.read_file", arguments={})
        )
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_SCHEMA_INVALID
        assert provider.calls == []

    def test_unknown_argument_is_rejected_before_provider(self) -> None:
        provider = _Provider()
        registry = ToolRegistry()
        registry.register(_manifest(), provider)
        result = registry.call(_call(path="a.txt", shell="rm -rf"))
        assert result.status is CallStatus.REJECTED
        assert provider.calls == []

    def test_success_has_call_id_duration_and_output(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider())
        call = _call()
        result = registry.call(call)
        assert result.call_id == call.call_id
        assert result.status is CallStatus.SUCCEEDED
        assert result.output == {"text": "hi"}
        assert result.duration_ms >= 0
        assert result.error is None

    def test_provider_error_becomes_structured_failure(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _manifest(),
            _Provider(error=SeraphimError(code=ErrorCode.TOOL_TIMEOUT, component="x", safe_message="too slow")),
        )
        result = registry.call(_call())
        assert result.status is CallStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.TOOL_TIMEOUT
        assert result.error.safe_message == "too slow"

    def test_unexpected_exception_does_not_leak_traceback(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider(error=RuntimeError("secret=abc")))
        result = registry.call(_call())
        assert result.status is CallStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.INTERNAL_ERROR
        assert "secret" not in result.error.safe_message

    def test_non_object_output_is_a_failure(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider(output=["not", "object"]))
        result = registry.call(_call())
        assert result.status is CallStatus.FAILED

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [({"path": 7}, "arguments.path must be of type string"), ({"path": True}, "arguments.path must be of type string")],
        ids=["int-for-string", "bool-for-string"],
    )
    def test_wrong_argument_type_is_rejected_before_invoke(self, arguments, message) -> None:
        provider = _Provider()
        registry = ToolRegistry()
        registry.register(_manifest(), provider)
        result = registry.call(_call(**arguments))
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_SCHEMA_INVALID
        assert provider.calls == []

    def test_bool_is_not_accepted_as_number(self) -> None:
        manifest = _manifest(
            input_schema={"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        )
        registry = ToolRegistry()
        registry.register(manifest, _Provider())
        assert registry.call(_call(n=True)).status is CallStatus.REJECTED

    def test_output_violating_output_schema_is_a_failure(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider(output={"text": 5}))
        result = registry.call(_call())
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_SCHEMA_INVALID

    def test_timeout_is_enforced(self) -> None:
        import threading

        gate = threading.Event()

        class _Hang:
            def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
                gate.wait(5)
                return {"text": "late"}

        registry = ToolRegistry()
        registry.register(_manifest(timeout=1), _Hang())
        result = registry.call(_call())
        gate.set()
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_TIMEOUT

    @pytest.mark.parametrize("side_effects", ["write", "external", "destructive"])
    def test_side_effect_tools_fail_closed_without_aegis(self, side_effects: str) -> None:
        provider = _Provider()
        manifest = ToolManifest(**{**_manifest().__dict__, "side_effects": side_effects, "risk": "high"})
        registry = ToolRegistry()
        registry.register(manifest, provider)
        result = registry.call(_call())
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and result.error.code == ErrorCode.TOOL_PERMISSION_DENIED
        assert provider.calls == []

    def test_manifest_schema_version_is_recorded_and_checked(self) -> None:
        assert _manifest().to_dict()["schema_version"] == 1
        with pytest.raises(SeraphimError) as exc:
            ToolManifest(**{**_manifest().__dict__, "schema_version": 2})
        assert exc.value.code == ErrorCode.TOOL_SCHEMA_INVALID

    def test_result_dict_has_single_format_for_every_status(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider())
        keys = set(registry.call(_call()).to_dict())
        rejected = set(registry.call(_call("tool.fs.ghost")).to_dict())
        assert keys == rejected == {
            "call_id", "tool_id", "status", "duration_ms", "output", "artifact_refs", "error",
        }


class TestDiscovery:
    def test_describe_is_available_for_core_and_ui(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider())
        described = registry.describe("tool.fs.read_file")
        assert described["id"] == "tool.fs.read_file"
        assert described["input_schema"]["required"] == ["path"]
        assert described["enabled"] is True

    def test_registry_holds_no_task_or_ui_state(self) -> None:
        registry = ToolRegistry()
        registry.register(_manifest(), _Provider())
        assert set(vars(registry)) == {"_entries", "_clock"}
