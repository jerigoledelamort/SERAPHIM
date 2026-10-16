# SERAPHIM OBSERVATORY — Logger tests (S06).
# Acceptance: secrets MUST NOT leak into logs (TB-7).

import json
import logging
from io import StringIO

from seraphim.contracts.sanitization import SecretRedactor, register_known_secret
from seraphim.observatory.logger import Logger


def test_logger_info_basic() -> None:
    """Test basic INFO logging."""
    logger = Logger("test_component")
    # Just verify it doesn't crash
    logger.info("Test message", user_id="u123")


def test_logger_all_levels() -> None:
    """Test all log levels work."""
    logger = Logger("test")
    logger.info("Info message")
    logger.warn("Warn message")
    logger.error("Error message")
    logger.critical("Critical message")


def test_logger_secret_redaction_in_message() -> None:
    """CRITICAL: API keys in message MUST be redacted."""
    logger = Logger("test")

    # Capture log output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    test_logger = logging.getLogger("seraphim.test")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    try:
        # Log message with secret
        logger.info("Connecting with api_key=sk-secret123456")

        # Check output
        output = stream.getvalue()
        assert "sk-secret123456" not in output, "Secret leaked into logs!"
        assert "[REDACTED]" in output, "Redaction marker missing"
    finally:
        test_logger.removeHandler(handler)


def test_logger_secret_redaction_in_fields() -> None:
    """CRITICAL: Secrets in fields MUST be redacted."""
    logger = Logger("test")

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    test_logger = logging.getLogger("seraphim.test")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    try:
        # Log with secret fields
        logger.info(
            "API call",
            api_key="sk-secret123",
            auth_token="bearer-xyz789",
            user_name="alice",  # Not a secret
        )

        output = stream.getvalue()
        assert "sk-secret123" not in output, "API key leaked!"
        assert "bearer-xyz789" not in output, "Auth token leaked!"
        assert "[REDACTED]" in output, "Redaction marker missing"
        assert "alice" in output, "Non-secret field missing"
    finally:
        test_logger.removeHandler(handler)


def test_logger_structured_output() -> None:
    """Test log output is valid JSON."""
    logger = Logger("test_comp")

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    test_logger = logging.getLogger("seraphim.test_comp")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    try:
        logger.info("Test event", task_id="t123", count=42)

        output = stream.getvalue().strip()
        # Parse as JSON
        record = json.loads(output)

        assert record["component"] == "test_comp"
        assert record["level"] == "INFO"
        assert record["message"] == "Test event"
        assert record["task_id"] == "t123"
        assert record["count"] == 42
    finally:
        test_logger.removeHandler(handler)


def test_logger_marker_secret_redaction() -> None:
    """CRITICAL: Test marker secret from acceptance criteria.

    User manual verification: search for SERAPHIM_TEST_SECRET_xyz789 in logs.
    This test proves it's redacted.
    """
    MARKER_SECRET = "SERAPHIM_TEST_SECRET_xyz789"

    logger = Logger("test")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    test_logger = logging.getLogger("seraphim.test")
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.INFO)

    try:
        # Log with marker secret in multiple places
        logger.info(
            f"Processing with key={MARKER_SECRET}",
            api_key=MARKER_SECRET,
            config={"secret": MARKER_SECRET, "safe": "value"},
        )

        output = stream.getvalue()

        # MUST NOT appear in logs
        assert MARKER_SECRET not in output, f"MARKER SECRET {MARKER_SECRET} LEAKED INTO LOGS!"
        # Redaction marker MUST appear
        assert "[REDACTED]" in output, "Redaction not applied"

    finally:
        test_logger.removeHandler(handler)


def test_logger_known_secret_redacted_without_pattern() -> None:
    """S09: a secret known to the process is redacted even without a pattern.

    Pattern matching alone would miss a bare marker value in free text; the
    SecretRedactor closes that gap for values read from the secret store.
    """
    marker = "SERAPHIM_TEST_SECRET_xyz789"
    redactor = SecretRedactor([marker])
    logger = Logger("test_known", redactor=redactor)

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    target = logging.getLogger("seraphim.test_known")
    target.addHandler(handler)
    target.setLevel(logging.INFO)

    try:
        logger.info(f"connecting with {marker} please ignore", note=marker)
        output = stream.getvalue()
        assert marker not in output, "Known secret leaked into logs!"
        assert "[REDACTED]" in output
    finally:
        target.removeHandler(handler)


def test_logger_without_redactor_still_pattern_scrubs() -> None:
    """The redactor is optional; the default path keeps pattern redaction."""
    logger = Logger("test_plain")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    target = logging.getLogger("seraphim.test_plain")
    target.addHandler(handler)
    target.setLevel(logging.INFO)

    try:
        logger.info("key sk-abcdef1234567890abcdef")
        output = stream.getvalue()
        assert "sk-abcdef1234567890abcdef" not in output
        assert "[REDACTED]" in output
    finally:
        target.removeHandler(handler)


def test_logger_without_redactor_scrubs_registered_secret() -> None:
    """S09 review F1: no ``redactor`` argument is needed for a store-read value.

    Registering a value (which the secret store does on every read) is enough
    for the default logger path to remove it — even in free text under a neutral
    field name, where no pattern would match.
    """
    marker = "SERAPHIM_TEST_SECRET_xyz789"
    register_known_secret(marker)
    logger = Logger("test_registry")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    target = logging.getLogger("seraphim.test_registry")
    target.addHandler(handler)
    target.setLevel(logging.INFO)

    try:
        logger.info(f"connecting with {marker} please ignore", note=marker)
        output = stream.getvalue()
        assert marker not in output, "Registered secret leaked into logs!"
        assert "[REDACTED]" in output
    finally:
        target.removeHandler(handler)
