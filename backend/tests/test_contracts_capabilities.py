# S04 tests — capability model.

import pytest
from seraphim.contracts.capabilities import Capability, validate_capability_id
from seraphim.contracts.errors import ErrorCode, SeraphimError


class TestValidateCapabilityId:
    @pytest.mark.parametrize(
        "cap_id",
        [
            "filesystem.read_file",
            "cad.geometry.inspect",
            "browser.tab.open",
            "shell.execute",
            "application.connect",
            "a.b",
        ],
    )
    def test_valid_ids(self, cap_id: str) -> None:
        assert validate_capability_id(cap_id) == cap_id

    @pytest.mark.parametrize(
        "cap_id",
        [
            "",
            "UPPER.case",
            "no_dot",
            ".leading_dot",
            "trailing_dot.",
            "a.b.c.d",
            "has space.here",
            "has-dash.here",
        ],
    )
    def test_invalid_ids(self, cap_id: str) -> None:
        with pytest.raises(ValueError, match="Invalid capability ID"):
            validate_capability_id(cap_id)

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError):
            validate_capability_id(42)  # type: ignore[arg-type]


class TestCapabilityConstruction:
    def test_minimal_valid(self) -> None:
        cap = Capability(id="filesystem.read_file", name="Read File")
        assert cap.id == "filesystem.read_file"
        assert cap.risk == "low"
        assert cap.timeout_seconds == 30

    def test_full_valid(self) -> None:
        cap = Capability(
            id="shell.execute",
            name="Execute Shell",
            description="Run a shell command",
            permissions=["shell.execute"],
            risk="high",
            side_effects="external",
            supports_cancellation=True,
            timeout_seconds=60,
        )
        assert cap.risk == "high"

    def test_invalid_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid capability ID"):
            Capability(id="INVALID", name="Bad")

    def test_invalid_risk_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Capability(id="a.b", name="Test", risk="extreme")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_invalid_side_effects_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Capability(id="a.b", name="Test", side_effects="explode")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_empty_name_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Capability(id="a.b", name="")
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_zero_timeout_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Capability(id="a.b", name="Test", timeout_seconds=0)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED

    def test_negative_timeout_raises(self) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            Capability(id="a.b", name="Test", timeout_seconds=-1)
        assert exc_info.value.code == ErrorCode.VALIDATION_FAILED


class TestCapabilitySerialization:
    def test_to_dict(self) -> None:
        cap = Capability(id="filesystem.read_file", name="Read", permissions=["filesystem.read"])
        d = cap.to_dict()
        assert d["id"] == "filesystem.read_file"
        assert d["permissions"] == ["filesystem.read"]

    def test_round_trip(self) -> None:
        original = Capability(
            id="cad.feature.create",
            name="Create Feature",
            risk="medium",
            side_effects="write",
            timeout_seconds=120,
        )
        data = original.to_dict()
        restored = Capability.from_dict(data)
        assert restored.id == original.id
        assert restored.risk == original.risk
        assert restored.timeout_seconds == original.timeout_seconds
