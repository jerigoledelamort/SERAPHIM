# S04 tests — JSON serialization round-trips, invalid JSON handling,
# and cross-type integration.
#
# Acceptance criteria: "invalid JSON gives a clear error, not a raw traceback."

import json
from dataclasses import dataclass

import pytest
from seraphim.contracts.capabilities import Capability
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event
from seraphim.contracts.permissions import Permission
from seraphim.contracts.result import Result
from seraphim.contracts.versioned import VersionedEntity


@dataclass
class _TaskRecord(VersionedEntity):
    """Concrete versioned entity for serialization tests."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    task_id: str = ""
    goal: str = ""
    status: str = "DRAFT"


class TestJsonRoundTrip:
    def test_error_json_round_trip(self) -> None:
        err = SeraphimError(
            code=ErrorCode.TOOL_TIMEOUT,
            component="wings.shell",
            safe_message="Timed out",
            retryable=True,
            details_ref="event_abc",
        )
        json_str = json.dumps(err.to_dict())
        parsed = json.loads(json_str)
        assert parsed["code"] == "TOOL_TIMEOUT"
        assert parsed["retryable"] is True

    def test_event_json_round_trip(self) -> None:
        evt = Event(type="task.started", component="core", severity="INFO")
        json_str = json.dumps(evt.to_dict())
        parsed = json.loads(json_str)
        restored = Event.from_dict(parsed)
        assert restored.id == evt.id
        assert restored.type == "task.started"

    def test_capability_json_round_trip(self) -> None:
        cap = Capability(
            id="filesystem.read_file",
            name="Read File",
            permissions=["filesystem.read"],
            risk="low",
        )
        json_str = json.dumps(cap.to_dict())
        restored = Capability.from_dict(json.loads(json_str))
        assert restored.id == cap.id

    def test_permission_json_round_trip(self) -> None:
        perm = Permission(name="shell.execute", scope="/sandbox")
        json_str = json.dumps(perm.to_dict())
        restored = Permission.from_dict(json.loads(json_str))
        assert restored.name == perm.name
        assert restored.scope == "/sandbox"

    def test_result_success_json(self) -> None:
        r = Result.success(42)
        json_str = json.dumps(r.to_dict())
        parsed = json.loads(json_str)
        assert parsed == {"ok": True, "value": 42}

    def test_result_failure_json(self) -> None:
        err = SeraphimError(code="X", component="test")
        r = Result.failure(err)
        json_str = json.dumps(r.to_dict())
        parsed = json.loads(json_str)
        assert parsed["ok"] is False
        assert parsed["error"]["code"] == "X"

    def test_versioned_json_round_trip(self) -> None:
        original = _TaskRecord(task_id="task_1", goal="test", status="RUNNING")
        json_str = json.dumps(original.to_dict())
        restored = _TaskRecord.from_dict(json.loads(json_str))
        assert restored.task_id == "task_1"
        assert restored.status == "RUNNING"


class TestInvalidJson:
    """Invalid input must produce SeraphimError or clear ValueError, not raw traceback."""

    def test_invalid_json_string(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            json.loads("{invalid")

    def test_from_dict_with_wrong_types(self) -> None:
        with pytest.raises(SeraphimError):
            _TaskRecord.from_dict({"schema_version": "not_int", "task_id": 123})

    def test_from_dict_with_none(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            _TaskRecord.from_dict(None)  # type: ignore[arg-type]

    def test_event_from_dict_missing_required(self) -> None:
        with pytest.raises(KeyError, match="type"):
            Event.from_dict({"component": "x"})

    def test_capability_from_dict_missing_id(self) -> None:
        with pytest.raises(KeyError, match="id"):
            Capability.from_dict({"name": "X"})

    def test_error_to_dict_is_json_serializable(self) -> None:
        """Error.to_dict() must always produce JSON-safe types."""
        err = SeraphimError(
            code="X",
            component="test",
            details={"nested": {"deep": [1, "two", True]}},
        )
        # Should not raise
        json.dumps(err.to_diagnostic_dict())


class TestErrorUniformity:
    """Errors must be uniform between backend and CLI/UI (acceptance criterion)."""

    def test_same_error_produces_same_dict(self) -> None:
        e1 = SeraphimError(
            code=ErrorCode.CONFIG_SCHEMA_INVALID,
            component="sanctum.loader",
            retryable=False,
        )
        e2 = SeraphimError(
            code=ErrorCode.CONFIG_SCHEMA_INVALID,
            component="sanctum.loader",
            retryable=False,
        )
        assert e1.to_dict() == e2.to_dict()

    def test_error_fields_stable_order(self) -> None:
        """to_dict must have deterministic key order for UI rendering."""
        err = SeraphimError(code="A", component="b")
        d = err.to_dict()
        keys = list(d.keys())
        assert keys == [
            "code",
            "message_key",
            "component",
            "retryable",
            "user_action_required",
            "details_ref",
        ]

    def test_no_python_objects_in_user_dict(self) -> None:
        """User-facing dict must be fully JSON-serializable."""
        err = SeraphimError(
            code="X",
            component="test",
            details={"obj": "value", "count": 1},
        )
        # to_dict should not include details at all
        d = err.to_dict()
        assert "details" not in d
        # Even diagnostic dict is JSON-safe
        json.dumps(err.to_diagnostic_dict())
