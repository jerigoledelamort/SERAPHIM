# S04 tests — Result envelope.

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.contracts.result import Result


class TestResultSuccess:
    def test_success_holds_value(self) -> None:
        r: Result[int] = Result.success(42)
        assert r.ok is True
        assert r.value == 42
        assert r.error is None

    def test_unwrap_returns_value(self) -> None:
        r = Result.success("hello")
        assert r.unwrap() == "hello"

    def test_success_none_value(self) -> None:
        r: Result[None] = Result.success(None)
        assert r.ok is True
        with pytest.raises(SeraphimError, match="value is None"):
            r.unwrap()


class TestResultFailure:
    def test_failure_holds_error(self) -> None:
        err = SeraphimError(code="X", component="test", safe_message="oops")
        r = Result.failure(err)
        assert r.ok is False
        assert r.error is err
        assert r.value is None

    def test_unwrap_raises_error(self) -> None:
        err = SeraphimError(code="MY_ERR", component="test", safe_message="bad")
        r = Result.failure(err)
        with pytest.raises(SeraphimError, match="bad"):
            r.unwrap()

    def test_failure_no_error_raises_internal(self) -> None:
        r = Result(ok=False)
        with pytest.raises(SeraphimError, match="no error"):
            r.unwrap()


class TestResultSerialization:
    def test_success_to_dict(self) -> None:
        r = Result.success({"key": "val"})
        d = r.to_dict()
        assert d == {"ok": True, "value": {"key": "val"}}

    def test_failure_to_dict_safe(self) -> None:
        err = SeraphimError(
            code="X",
            component="test",
            correlation_id="corr_1",
        )
        r = Result.failure(err)
        d = r.to_dict()
        assert d["ok"] is False
        assert d["error"]["code"] == "X"
        # correlation_id must not leak to user-safe dict
        assert "correlation_id" not in d["error"]

    def test_diagnostic_dict(self) -> None:
        err = SeraphimError(code="X", component="test", correlation_id="c1")
        r = Result.failure(err)
        d = r.to_diagnostic_dict()
        assert d["error"]["correlation_id"] == "c1"

    def test_value_serialization_fallback(self) -> None:
        r = Result.success(object())
        d = r.to_dict()
        assert isinstance(d["value"], str)  # str() fallback


class TestResultRepr:
    def test_ok_repr(self) -> None:
        assert "Result.ok" in repr(Result.success(1))

    def test_err_repr(self) -> None:
        err = SeraphimError(code="X", component="test")
        assert "Result.err" in repr(Result.failure(err))
