# S04 tests — sanitization: secrets and stack traces must not leak.


from seraphim.contracts.sanitization import (
    REDACTED,
    SecretRedactor,
    clear_known_secrets,
    known_secret_count,
    redact_known_secrets,
    register_known_secret,
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


class TestProviderKeyPatterns:
    """S09: additional provider key formats must be recognized."""

    def test_anthropic_key_redacted(self) -> None:
        result = sanitize_text("key sk-ant-api03-abcdefghijklmnopqrstuv")
        assert "sk-ant-api03" not in result
        assert REDACTED in result

    def test_google_key_redacted(self) -> None:
        result = sanitize_text("AIzaSyA1234567890abcdefghijklmnopqrstuv")
        assert "AIzaSyA" not in result

    def test_huggingface_token_redacted(self) -> None:
        result = sanitize_text("hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        assert "hf_ABCDEF" not in result

    def test_github_token_redacted(self) -> None:
        result = sanitize_text("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        assert "ghp_ABCDEF" not in result

    def test_slack_token_redacted(self) -> None:
        result = sanitize_text("xoxb-1234567890-abcdefghijkl")
        assert "xoxb-1234567890" not in result

    def test_jwt_redacted(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        result = sanitize_text(f"Authorization: {token}")
        assert "eyJhbGciOiJIUzI1NiJ9" not in result


class TestRedactKnownSecrets:
    """S09: values known to the process are removed by exact match."""

    def test_known_value_redacted_without_pattern(self) -> None:
        marker = "SERAPHIM_TEST_SECRET_xyz789"
        # No "key=" prefix: pattern matching alone would miss this.
        assert marker in sanitize_text(f"the value is {marker}")
        result = redact_known_secrets(f"the value is {marker}", [marker])
        assert marker not in result
        assert REDACTED in result

    def test_short_values_are_not_masked(self) -> None:
        # Short strings are labels, not secrets; masking them would be noise.
        assert redact_known_secrets("abc def", ["abc"]) == "abc def"

    def test_accepts_single_string(self) -> None:
        marker = "MARKER-VALUE-12345678"
        assert marker not in redact_known_secrets(f"x {marker} y", marker)

    def test_longest_match_wins(self) -> None:
        short, long = "SECRET-12345678", "SECRET-12345678-EXTENDED"
        result = redact_known_secrets(f"value {long}", [short, long])
        assert long not in result
        assert REDACTED in result

    def test_none_is_noop(self) -> None:
        assert redact_known_secrets("plain text", None) == "plain text"

    def test_redactor_combines_patterns_and_known_values(self) -> None:
        marker = "SERAPHIM_TEST_SECRET_xyz789"
        redactor = SecretRedactor([marker])
        assert redactor.known_count == 1
        result = redactor.redact(f"sk-abcdef1234567890abcdef and {marker}")
        assert marker not in result
        assert "sk-abcdef1234567890abcdef" not in result

    def test_redactor_dict_deep(self) -> None:
        marker = "SERAPHIM_TEST_SECRET_xyz789"
        redactor = SecretRedactor([marker])
        result = redactor.redact_dict({"a": {"b": [marker, "safe"]}, "c": "safe"})
        assert result["a"]["b"][0] == REDACTED
        assert result["a"]["b"][1] == "safe"
        assert result["c"] == "safe"


class TestKnownSecretRegistry:
    """S09 review F1: a value read into the process is redacted everywhere.

    The generic sinks (``SeraphimError``, ``Logger``, ``Event``, exports) only
    apply ``sanitize_text``/``sanitize_dict``.  Registration is what makes the
    guarantee structural instead of depending on every caller.
    """

    MARKER = "SERAPHIM_TEST_SECRET_xyz789"

    def test_registered_value_is_redacted_by_sanitize_text(self) -> None:
        assert self.MARKER in sanitize_text(f"the value is {self.MARKER}")
        register_known_secret(self.MARKER)
        assert self.MARKER not in sanitize_text(f"the value is {self.MARKER}")

    def test_registered_value_is_redacted_under_neutral_key(self) -> None:
        register_known_secret(self.MARKER)
        result = sanitize_dict({"note": f"value is {self.MARKER}", "safe": "ok"})
        assert self.MARKER not in result["note"]
        assert result["safe"] == "ok"

    def test_registered_value_is_redacted_by_redact_known_secrets(self) -> None:
        register_known_secret(self.MARKER)
        assert self.MARKER not in redact_known_secrets(f"x {self.MARKER} y", None)

    def test_short_registered_value_is_ignored(self) -> None:
        register_known_secret("abc")
        assert known_secret_count() == 0

    def test_clear_removes_registered_values(self) -> None:
        register_known_secret(self.MARKER)
        assert known_secret_count() == 1
        clear_known_secrets()
        assert known_secret_count() == 0
        assert self.MARKER in sanitize_text(f"the value is {self.MARKER}")


class TestReferenceKeyValues:
    """S09 review F2: only reference-shaped values survive under *_ref keys."""

    def test_valid_reference_is_kept(self) -> None:
        result = sanitize_dict({"secret_ref": "provider.openai"})
        assert result["secret_ref"] == "provider.openai"

    def test_value_that_is_not_reference_shaped_is_redacted(self) -> None:
        for literal in ("Not A Ref", "UPPER", "../../etc/passwd", "ref/with/slash"):
            assert sanitize_dict({"secret_ref": literal})["secret_ref"] == REDACTED

    def test_pattern_like_value_under_reference_key_is_redacted(self) -> None:
        result = sanitize_dict({"secret_ref": "sk-ant-api03-abcdefghijklmnopqrstuv"})
        assert result["secret_ref"] == REDACTED

    def test_registered_secret_under_reference_key_is_redacted(self) -> None:
        # A pattern-free credential can look exactly like a reference, so the
        # shape check cannot decide alone: once the process knows the value, it
        # is redacted even here.
        literal = "abcdef0123456789abcdef0123456789"
        register_known_secret(literal)
        assert sanitize_dict({"secret_ref": literal})["secret_ref"] == REDACTED

    def test_other_reference_keys_are_covered(self) -> None:
        for key in ("credential_ref", "key_ref", "token_ref"):
            assert sanitize_dict({key: "not a ref"})[key] == REDACTED

    def test_non_string_reference_value_is_redacted(self) -> None:
        result = sanitize_dict({"secret_ref": {"inner": "not a ref"}})
        assert result["secret_ref"] == REDACTED


class TestReferencePatternStaysInSync:
    """The reference pattern is duplicated in contracts and sanctum (no import)."""

    def test_patterns_match(self) -> None:
        from seraphim.contracts.sanitization import _SECRET_REF_VALUE_RE
        from seraphim.sanctum.secrets import SECRET_REF_PATTERN

        assert _SECRET_REF_VALUE_RE.pattern == SECRET_REF_PATTERN.pattern
