# S04 tests — ID generation and validation.

import pytest
from seraphim.contracts.ids import generate_id, id_prefix, validate_id


class TestGenerateId:
    def test_generates_valid_uuid_id(self) -> None:
        id_str = generate_id("task")
        assert id_str.startswith("task_")
        assert len(id_str) > 5

    def test_unique_ids(self) -> None:
        ids = {generate_id("event") for _ in range(100)}
        assert len(ids) == 100

    def test_unknown_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown ID prefix"):
            generate_id("bogus")

    @pytest.mark.parametrize("prefix", ["task", "step", "call", "event", "session"])
    def test_known_prefixes(self, prefix: str) -> None:
        id_str = generate_id(prefix)
        assert id_str.startswith(f"{prefix}_")


class TestValidateId:
    def test_valid_id_passes(self) -> None:
        id_str = generate_id("task")
        assert validate_id(id_str) == id_str

    def test_no_prefix_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ID format"):
            validate_id("no_prefix_here")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ID format"):
            validate_id("")

    def test_unknown_prefix_in_valid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown ID prefix"):
            validate_id("bogus_12345678-1234-1234-1234-123456789abc")

    def test_non_string_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="ID must be a string"):
            validate_id(42)  # type: ignore[arg-type]

    def test_uppercase_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid ID format"):
            validate_id("TASK_12345678-1234-1234-1234-123456789abc")


class TestIdPrefix:
    def test_extracts_prefix(self) -> None:
        id_str = generate_id("task")
        assert id_prefix(id_str) == "task"

    def test_extracts_multi_word_prefix(self) -> None:
        id_str = generate_id("correlation")
        assert id_prefix(id_str) == "correlation"

    def test_invalid_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract prefix"):
            id_prefix("not_valid")
