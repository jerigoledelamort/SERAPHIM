# WINGS registry (S19): registers tool manifests, answers discovery queries and
# executes enabled tools through their provider. Authorization is injected as a
# PolicyGate callable (S20, AEGIS); the registry never imports AEGIS rule types.

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.wings.calls import CallStatus, ToolCall, ToolError, ToolResult
from seraphim.wings.manifest import ToolManifest

PolicyGate = Callable[[ToolManifest, ToolCall], Any]

COMPONENT = "wings.registry"


class ToolProvider(Protocol):
    """Implemented by MCP, BRIDGES and built-in tools. Receives validated arguments only."""

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class _Entry:
    manifest: ToolManifest
    provider: ToolProvider
    enabled: bool = True


@dataclass
class ToolRegistry:
    _entries: dict[str, _Entry] = field(default_factory=dict)
    _clock: Callable[[], float] = time.monotonic

    def pinned(self):
        return ToolRegistry({key: _Entry(copy.deepcopy(entry.manifest), entry.provider, entry.enabled)
                             for key, entry in self._entries.items()}, self._clock)

    def register(self, manifest: ToolManifest, provider: ToolProvider, *, enabled: bool = True) -> None:
        if manifest.id in self._entries:
            raise SeraphimError(
                code=ErrorCode.REGISTRY_CONFLICT,
                component=COMPONENT,
                safe_message=f"Tool {manifest.id} is already registered",
            )
        self._check_capability_conflict(manifest)
        self._entries[manifest.id] = _Entry(manifest=manifest, provider=provider, enabled=enabled)

    def unregister(self, tool_id: str) -> None:
        self._get(tool_id)
        del self._entries[tool_id]

    def enable(self, tool_id: str) -> None:
        self._get(tool_id).enabled = True

    def disable(self, tool_id: str) -> None:
        self._get(tool_id).enabled = False

    def is_enabled(self, tool_id: str) -> bool:
        return self._get(tool_id).enabled

    def manifest(self, tool_id: str) -> ToolManifest:
        return self._get(tool_id).manifest

    def discover(self, *, include_disabled: bool = False) -> list[ToolManifest]:
        return [
            e.manifest
            for tool_id, e in sorted(self._entries.items())
            if include_disabled or e.enabled
        ]

    def describe(self, tool_id: str) -> dict[str, Any]:
        entry = self._get(tool_id)
        return {**entry.manifest.to_dict(), "enabled": entry.enabled}

    def policy_resources(self, manifest: ToolManifest, call: ToolCall) -> tuple[str, ...]:
        resolver = getattr(self._get(manifest.id).provider, "policy_resources", None)
        return tuple(resolver(manifest, call.arguments)) if resolver else ()

    def validate(self, call: ToolCall) -> ToolResult | None:
        original = self._entries.get(call.tool_id)
        entry = _Entry(copy.deepcopy(original.manifest), original.provider, original.enabled) if original else None
        if entry is None:
            return _rejected(call, ErrorCode.TOOL_NOT_FOUND, "Tool is not registered.")
        if not entry.enabled:
            return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "Tool is disabled.")
        try:
            _check_value(entry.manifest.input_schema, call.arguments, "arguments")
        except (SeraphimError, ValueError, TypeError, KeyError):
            return _rejected(call, ErrorCode.TOOL_SCHEMA_INVALID, "Tool arguments do not match the schema.")
        return None

    def call(
        self, call: ToolCall, *, policy: PolicyGate | None = None,
        timeout_seconds: float | None = None,
    ) -> ToolResult:
        original = self._entries.get(call.tool_id)
        entry = _Entry(copy.deepcopy(original.manifest), original.provider, original.enabled) if original else None
        if entry is None:
            return _rejected(call, ErrorCode.TOOL_NOT_FOUND, "Tool is not registered.")
        if not entry.enabled:
            return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "Tool is disabled.")
        if policy is None:
            return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "No policy decision was made for this call.")
        try:
            decision = policy(entry.manifest, call)
        except Exception:
            return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "Policy could not be evaluated for this call.")
        if not decision.allowed:
            return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, decision.reason)
        try:
            _check_value(entry.manifest.input_schema, call.arguments, "arguments")
        except SeraphimError as exc:
            return _rejected(call, ErrorCode.TOOL_SCHEMA_INVALID, exc.safe_message)
        timeout = entry.manifest.timeout_seconds
        limits = getattr(decision, "limits", None)
        if limits is not None:
            if limits.allowed_roots:
                resolver = getattr(entry.provider, "policy_resources", None)
                try:
                    resources = resolver(entry.manifest, call.arguments) if resolver else ()
                    from pathlib import Path

                    roots = tuple(Path(root).resolve() for root in limits.allowed_roots)
                    if not resources or any(
                        not any(Path(resource).resolve().is_relative_to(root) for root in roots)
                        for resource in resources
                    ):
                        return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "Policy roots cannot authorize this resource.")
                except Exception:
                    return _rejected(call, ErrorCode.TOOL_PERMISSION_DENIED, "Policy resources cannot be resolved.")
            if limits.timeout_seconds is not None:
                timeout = min(timeout, limits.timeout_seconds)
        if timeout_seconds is not None:
            timeout = min(timeout, timeout_seconds)
        if timeout <= 0:
            return _rejected(call, ErrorCode.TOOL_TIMEOUT, "Execution deadline expired before invocation.")
        started = self._clock()
        try:
            output = _invoke_with_timeout(entry, call.arguments, timeout)
        except TimeoutError:
            return _failed(
                call, started, self._clock(), ErrorCode.TOOL_TIMEOUT,
                "Tool exceeded its timeout; it may still be running and its outcome is unknown.",
            )
        except SeraphimError as exc:
            return _failed(call, started, self._clock(), exc.code, exc.safe_message)
        except Exception as exc:
            return _failed(call, started, self._clock(), ErrorCode.INTERNAL_ERROR, type(exc).__name__)
        duration = _ms(started, self._clock())
        try:
            _check_value(entry.manifest.output_schema, output, "output")
        except SeraphimError as exc:
            return _failed(call, started, self._clock(), ErrorCode.TOOL_SCHEMA_INVALID, exc.safe_message)
        if call.tool_id == "tool.process.run" and (
            output.get("exit_code") != 0 or output.get("timed_out") or output.get("cancelled")
        ):
            return ToolResult(
                call_id=call.call_id, tool_id=call.tool_id, status=CallStatus.FAILED,
                duration_ms=duration, output=output,
                error=ToolError(code=ErrorCode.INTERNAL_ERROR,
                                safe_message="Process did not complete successfully."),
            )
        return ToolResult(
            call_id=call.call_id,
            tool_id=call.tool_id,
            status=CallStatus.SUCCEEDED,
            duration_ms=duration,
            output=output,
        )

    def _get(self, tool_id: str) -> _Entry:
        entry = self._entries.get(tool_id)
        if entry is None:
            raise SeraphimError(
                code=ErrorCode.TOOL_NOT_FOUND,
                component=COMPONENT,
                safe_message=f"Tool {tool_id} is not registered",
            )
        return entry

    def _check_capability_conflict(self, manifest: ToolManifest) -> None:
        for other in self._entries.values():
            if other.manifest.source == manifest.source:
                continue
            clash = sorted(set(other.manifest.capabilities) & set(manifest.capabilities))
            if clash:
                raise SeraphimError(
                    code=ErrorCode.REGISTRY_CONFLICT,
                    component=COMPONENT,
                    safe_message=(
                        f"Capability {clash[0]} is already provided by {other.manifest.id} "
                        f"from source {other.manifest.source}"
                    ),
                )


def _ms(start: float, end: float) -> int:
    return max(0, int((end - start) * 1000))


def _rejected(call: ToolCall, code: str, message: str) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_id=call.tool_id,
        status=CallStatus.REJECTED,
        duration_ms=0,
        error=ToolError(code=code, safe_message=message),
    )


def _failed(call: ToolCall, started: float, ended: float, code: str, message: str) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_id=call.tool_id,
        status=CallStatus.FAILED,
        duration_ms=_ms(started, ended),
        error=ToolError(code=code, safe_message=message),
    )


def _invoke_with_timeout(entry: _Entry, arguments: dict[str, Any], timeout: float) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["output"] = entry.provider.invoke(entry.manifest, dict(arguments))
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(entry.manifest.id)
    if "error" in box:
        raise box["error"]
    return box.get("output")


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _check_value(schema: dict[str, Any], value: Any, where: str) -> None:
    declared = schema.get("type")
    if declared is None:
        return
    if not _matches_type(declared, value):
        raise SeraphimError(
            code=ErrorCode.TOOL_SCHEMA_INVALID,
            component=COMPONENT,
            safe_message=f"{where} must be of type {declared}",
        )
    if declared != "object":
        return
    properties = schema.get("properties", {})
    missing = [name for name in schema.get("required", []) if name not in value]
    if missing:
        raise SeraphimError(
            code=ErrorCode.TOOL_SCHEMA_INVALID,
            component=COMPONENT,
            safe_message=f"Missing required {where} field: {missing[0]}",
        )
    if where == "arguments" and properties:
        unknown = [name for name in value if name not in properties]
        if unknown:
            raise SeraphimError(
                code=ErrorCode.TOOL_SCHEMA_INVALID,
                component=COMPONENT,
                safe_message=f"Unknown argument: {unknown[0]}",
            )
    for name, sub in properties.items():
        if name in value and isinstance(sub, dict):
            _check_value(sub, value[name], f"{where}.{name}")


def _matches_type(declared: str, value: Any) -> bool:
    if declared in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPE_CHECKS[declared])
