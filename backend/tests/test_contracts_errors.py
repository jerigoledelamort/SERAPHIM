# S04 tests — structured error envelope.


from seraphim.contracts.errors import ErrorCode, SeraphimError


class TestSeraphimError:
    def test_basic_construction(self) -> None:
        err = SeraphimError(
            code=ErrorCode.PROVIDER_TIMEOUT,
            component="model_layer.openai",
            safe_message="Request timed out",
            retryable=True,
        )
        assert err.code == "PROVIDER_TIMEOUT"
        assert err.message_key == "errors.provider_timeout"
        assert err.component == "model_layer.openai"
        assert err.retryable is True
        assert err.user_action_required is False

    def test_is_exception(self) -> None:
        err = SeraphimError(code="X", component="test")
        assert isinstance(err, Exception)

    def test_str_fallback_to_code(self) -> None:
        err = SeraphimError(code="MY_CODE", component="test")
        assert str(err) == "MY_CODE"

    def test_str_uses_safe_message(self) -> None:
        err = SeraphimError(code="MY_CODE", component="test", safe_message="Readable msg")
        assert str(err) == "Readable msg"


class TestErrorToDict:
    def test_user_safe_fields_only(self) -> None:
        err = SeraphimError(
            code=ErrorCode.INTEGRATION_TIMEOUT,
            component="bridges.freecad",
            safe_message="Connection timed out",
            retryable=True,
            user_action_required=False,
            details_ref="event_abc",
            correlation_id="corr_123",
            task_id="task_456",
            tool_call_id="call_789",
            details={"path": "/home/user/file"},
        )
        d = err.to_dict()
        # Must contain §14.2 fields
        assert d["code"] == "INTEGRATION_TIMEOUT"
        assert d["message_key"] == "errors.integration_timeout"
        assert d["component"] == "bridges.freecad"
        assert d["retryable"] is True
        assert d["user_action_required"] is False
        assert d["details_ref"] == "event_abc"
        # Must NOT contain internal fields
        assert "correlation_id" not in d
        assert "task_id" not in d
        assert "tool_call_id" not in d
        assert "safe_message" not in d
        assert "sanitized_details" not in d

    def test_diagnostic_dict_includes_correlation(self) -> None:
        err = SeraphimError(
            code="X",
            component="test",
            correlation_id="corr_1",
            task_id="task_1",
        )
        d = err.to_diagnostic_dict()
        assert d["correlation_id"] == "corr_1"
        assert d["task_id"] == "task_1"
        # Still has user-safe fields
        assert d["code"] == "X"


class TestErrorSanitization:
    def test_secrets_in_details_are_redacted(self) -> None:
        err = SeraphimError(
            code="X",
            component="test",
            details={"api_key": "sk-abcdef1234567890abcdef", "path": "/safe"},
        )
        diag = err.to_diagnostic_dict()
        assert diag["sanitized_details"]["api_key"] == "[REDACTED]"
        assert diag["sanitized_details"]["path"] == "/safe"

    def test_no_stack_trace_in_to_dict(self) -> None:
        err = SeraphimError(
            code="X",
            component="test",
            safe_message="Traceback (most recent call last):\n  File secret.py",
        )
        d = err.to_dict()
        # safe_message is NOT in to_dict (user-safe only)
        assert "safe_message" not in d
        assert "Traceback" not in str(d)


class TestErrorFromException:
    def test_wraps_exception(self) -> None:
        exc = RuntimeError("boom")
        err = SeraphimError.from_exception(exc, component="test", task_id="task_1")
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert "RuntimeError" in err.safe_message
        assert "boom" in err.safe_message

    def test_no_traceback_leak(self) -> None:
        try:
            msg = "fail"
            raise ValueError(msg)
        except ValueError as exc:
            err = SeraphimError.from_exception(exc, component="test")
        # to_dict must not contain raw traceback
        d = err.to_dict()
        assert "File " not in str(d)
        assert "line " not in str(d)

    def test_multiline_exception_safe(self) -> None:
        exc = RuntimeError("first line\nsecond line\nthird line")
        err = SeraphimError.from_exception(exc, component="test")
        assert "\n" not in err.safe_message


class TestErrorCode:
    def test_all_codes_are_uppercase_snake(self) -> None:
        for attr in dir(ErrorCode):
            if attr.isupper():
                val = getattr(ErrorCode, attr)
                assert isinstance(val, str)
                assert val == val.upper()
                assert " " not in val

    def test_message_key_derivation(self) -> None:
        err = SeraphimError(code="PROVIDER_AUTH_FAILED", component="test")
        assert err.message_key == "errors.provider_auth_failed"
