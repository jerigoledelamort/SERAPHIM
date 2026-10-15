# S04 tests — versioned entity: schema version checks, backward compat,
# unknown field handling.

from dataclasses import dataclass

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.versioned import VersionedEntity


@dataclass
class SampleEntity(VersionedEntity):
    SCHEMA_VERSION = 2
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 2
    name: str = ""
    count: int = 0


class TestVersionedConstruction:
    def test_valid_version(self) -> None:
        e = SampleEntity(schema_version=1, name="a", count=1)
        assert e.schema_version == 1

    def test_current_version(self) -> None:
        e = SampleEntity(schema_version=2, name="b")
        assert e.schema_version == 2

    def test_too_old_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity(schema_version=0, name="x")
        assert exc_info.value.code == ErrorCode.CONTRACT_VERSION_UNSUPPORTED

    def test_too_new_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity(schema_version=3, name="x")
        assert exc_info.value.code == ErrorCode.CONTRACT_VERSION_UNSUPPORTED

    def test_non_int_version_raises(self) -> None:
        e = SampleEntity.__new__(SampleEntity)
        e.schema_version = "bad"  # type: ignore[assignment]
        with pytest.raises(SeraphimError) as exc_info:
            e._validate_schema_version()
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED


class TestVersionedToDict:
    def test_includes_schema_version(self) -> None:
        e = SampleEntity(schema_version=1, name="x", count=5)
        d = e.to_dict()
        assert d["schema_version"] == 1
        assert d["name"] == "x"
        assert d["count"] == 5


class TestVersionedFromDict:
    def test_round_trip(self) -> None:
        original = SampleEntity(schema_version=2, name="test", count=3)
        data = original.to_dict()
        restored = SampleEntity.from_dict(data)
        assert restored.name == "test"
        assert restored.count == 3
        assert restored.schema_version == 2

    def test_missing_schema_version_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity.from_dict({"name": "x"})
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED
        assert "schema_version" in exc_info.value.safe_message

    def test_non_int_schema_version_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity.from_dict({"schema_version": "two", "name": "x"})
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_future_version_rejected(self) -> None:
        """Unknown required fields from a future major must NOT be silently accepted."""
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity.from_dict({"schema_version": 99, "name": "x"})
        assert exc_info.value.code == ErrorCode.CONTRACT_VERSION_UNSUPPORTED
        assert exc_info.value.user_action_required is True

    def test_old_version_rejected(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            SampleEntity.from_dict({"schema_version": 0, "name": "x"})
        assert exc_info.value.code == ErrorCode.CONTRACT_VERSION_UNSUPPORTED

    def test_unknown_optional_preserved_round_trip(self) -> None:
        """Unknown optional field within supported range → preserve for round-trip."""
        data = {"schema_version": 1, "name": "x", "count": 1, "future_field": "keep_me"}
        obj = SampleEntity.from_dict(data)
        assert obj.name == "x"
        # Round-trip: to_dict should include the unknown field
        restored = obj.to_dict()
        assert restored["future_field"] == "keep_me"

    def test_missing_optional_field_uses_default(self) -> None:
        data = {"schema_version": 1, "name": "x"}
        obj = SampleEntity.from_dict(data)
        assert obj.count == 0  # default

    def test_extra_field_not_in_constructor(self) -> None:
        """Extra fields are NOT passed to __init__, avoiding TypeError."""
        data = {
            "schema_version": 1,
            "name": "y",
            "count": 2,
            "unknown1": 100,
            "unknown2": "s",
        }
        obj = SampleEntity.from_dict(data)
        assert obj.name == "y"
        assert not hasattr(obj, "unknown1")
