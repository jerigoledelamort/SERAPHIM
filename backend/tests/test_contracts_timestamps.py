# S04 tests — timestamp utilities.

import pytest
from seraphim.contracts.timestamps import now_utc, validate_timestamp


class TestNowUtc:
    def test_returns_string(self) -> None:
        ts = now_utc()
        assert isinstance(ts, str)

    def test_ends_with_z(self) -> None:
        ts = now_utc()
        assert ts.endswith("Z")

    def test_parseable(self) -> None:
        ts = now_utc()
        validate_timestamp(ts)  # should not raise


class TestValidateTimestamp:
    @pytest.mark.parametrize(
        "ts",
        [
            "2026-10-13T12:00:00Z",
            "2026-10-13T12:00:00.123Z",
            "2026-10-13T12:00:00+00:00",
            "2026-10-13T12:00:00.123456+03:00",
        ],
    )
    def test_valid_formats(self, ts: str) -> None:
        assert validate_timestamp(ts) == ts

    @pytest.mark.parametrize(
        "ts",
        [
            "not-a-date",
            "2026-13-01T00:00:00Z",
            "13.10.2026",
        ],
    )
    def test_invalid_formats_raise(self, ts: str) -> None:
        with pytest.raises(ValueError, match="Invalid ISO 8601"):
            validate_timestamp(ts)

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_timestamp("")

    def test_non_string_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="Timestamp must be a string"):
            validate_timestamp(12345)  # type: ignore[arg-type]
