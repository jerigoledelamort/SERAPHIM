# S04 tests — event metadata.

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event, Severity, validate_event_type


class TestValidateEventType:
    @pytest.mark.parametrize(
        "evt_type",
        [
            "task.created",
            "tool.call.started",
            "policy.decision",
            "memory.retrieval",
            "a.b",
        ],
    )
    def test_valid(self, evt_type: str) -> None:
        assert validate_event_type(evt_type) == evt_type

    @pytest.mark.parametrize(
        "evt_type",
        [
            "",
            "single",
            "UPPER.case",
            "a.b.c.d",
            "has space.here",
        ],
    )
    def test_invalid(self, evt_type: str) -> None:
        with pytest.raises(ValueError, match="Invalid event type"):
            validate_event_type(evt_type)


class TestEventConstruction:
    def test_minimal_valid(self) -> None:
        evt = Event(type="task.created", component="core")
        assert evt.id.startswith("event_")
        assert evt.timestamp.endswith("Z")
        assert evt.severity == "INFO"
        assert evt.schema_version == 1

    def test_full_valid(self) -> None:
        evt = Event(
            type="tool.call.completed",
            component="wings.filesystem",
            severity="INFO",
            task_id="task_12345678-1234-1234-1234-123456789abc",
            session_id="session_12345678-1234-1234-1234-123456789abc",
            correlation_id="corr_12345678-1234-1234-1234-123456789abc",
            payload={"duration_ms": 42},
        )
        assert evt.payload["duration_ms"] == 42

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid event type"):
            Event(type="INVALID", component="test")

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Event(type="a.b", component="test", severity="FATAL")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_empty_component_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Event(type="a.b", component="")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_payload_sanitized(self) -> None:
        evt = Event(
            type="a.b",
            component="test",
            payload={"api_key": "sk-abcdef1234567890abcdef", "safe": "ok"},
        )
        assert evt.payload["api_key"] == "[REDACTED]"
        assert evt.payload["safe"] == "ok"

    def test_severity_enum_values(self) -> None:
        for s in Severity:
            Event(type="a.b", component="test", severity=s.value)


class TestEventSerialization:
    def test_to_dict_has_required_fields(self) -> None:
        evt = Event(type="task.created", component="core")
        d = evt.to_dict()
        required = {
            "id",
            "timestamp",
            "type",
            "component",
            "severity",
            "schema_version",
            "payload",
        }
        assert required.issubset(d.keys())

    def test_round_trip(self) -> None:
        original = Event(
            type="tool.call.failed",
            component="wings.shell",
            severity="ERROR",
            task_id="task_12345678-1234-1234-1234-123456789abc",
        )
        data = original.to_dict()
        restored = Event.from_dict(data)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.severity == "ERROR"

    def test_from_dict_missing_type_raises(self) -> None:
        with pytest.raises(KeyError):
            Event.from_dict({"component": "test"})
