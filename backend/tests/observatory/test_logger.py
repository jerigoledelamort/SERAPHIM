# SERAPHIM OBSERVATORY — Logger tests (S06).
# Acceptance: secrets MUST NOT leak into logs (TB-7).

import json
import logging
from io import StringIO

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
