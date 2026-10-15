# S04 tests — sanitization: secrets and stack traces must not leak.


from seraphim.contracts.sanitization import (
    REDACTED,
    sanitize_dict,
    sanitize_text,
    strip_traceback,
)


class TestSanitizeText:
    def test_plain_text_unchanged(self) -> None:
        assert sanitize_text("Hello world") == "Hello world"

    def test_sk_api_key_redacted(self) -> None:
        text = "key is sk-abcdef1234567890abcdef"
        result = sanitize_text(text)
        assert "sk-abcdef" not in result
        assert REDACTED in result

    def test_bearer_token_redacted(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_text(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result

    def test_password_value_redacted(self) -> None:
        text = "password=super_secret_123"
        result = sanitize_text(text)
        assert "super_secret_123" not in result

    def test_empty_string(self) -> None:
        assert sanitize_text("") == ""


class TestSanitizeDict:
    def test_plain_dict_unchanged(self) -> None:
        data = {"name": "test", "count": 42}
        assert sanitize_dict(data) == data

    def test_api_key_key_redacted(self) -> None:
        data = {"api_key": "sk-1234567890abcdef", "name": "test"}
        result = sanitize_dict(data)
        assert result["api_key"] == REDACTED
        assert result["name"] == "test"

    def test_nested_secret_key_redacted(self) -> None:
        data = {"config": {"password": "hunter2", "host": "localhost"}}
        result = sanitize_dict(data)
        assert result["config"]["password"] == REDACTED
        assert result["config"]["host"] == "localhost"

    def test_list_values_sanitized(self) -> None:
        data = {"tokens": ["sk-abcdef1234567890abcdef", "safe_value"]}
        result = sanitize_dict(data)
        assert REDACTED in result["tokens"]
        assert "safe_value" in result["tokens"]

    def test_token_key_redacted(self) -> None:
        data = {"access_token": "abc123", "user": "admin"}
        result = sanitize_dict(data)
        assert result["access_token"] == REDACTED
        assert result["user"] == "admin"

    def test_authorization_key_redacted(self) -> None:
        data = {"Authorization": "Bearer xyz", "method": "GET"}
        result = sanitize_dict(data)
        assert result["Authorization"] == REDACTED

    def test_empty_dict(self) -> None:
        assert sanitize_dict({}) == {}


class TestStripTraceback:
    def test_single_line_unchanged(self) -> None:
        assert strip_traceback("Simple error") == "Simple error"

    def test_multiline_keeps_first(self) -> None:
        text = "ValueError: bad input\n  File foo.py, line 1\n  Traceback..."
        assert strip_traceback(text) == "ValueError: bad input"

    def test_empty_string(self) -> None:
        assert strip_traceback("") == ""
