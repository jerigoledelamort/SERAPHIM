# SERAPHIM OBSERVATORY — structured logging with redaction (S06).
# Spec TB-7: logs must not contain API keys, auth headers, secrets.

from __future__ import annotations

import json
import logging
from typing import Any

from seraphim.contracts.sanitization import sanitize_dict, sanitize_text

logger = logging.getLogger(__name__)


class Logger:
    """Structured logger with automatic secret redaction.

    All payloads are sanitized before logging.
    Uses Python logging infrastructure with structured JSON output.
    """

    def __init__(self, component: str) -> None:
        self.component = component
        self._logger = logging.getLogger(f"seraphim.{component}")

    def info(self, message: str, **fields: Any) -> None:
        """Log INFO with structured fields."""
        self._log("INFO", message, fields)

    def warn(self, message: str, **fields: Any) -> None:
        """Log WARN with structured fields."""
        self._log("WARN", message, fields)

    def error(self, message: str, **fields: Any) -> None:
        """Log ERROR with structured fields."""
        self._log("ERROR", message, fields)

    def critical(self, message: str, **fields: Any) -> None:
        """Log CRITICAL with structured fields."""
        self._log("CRITICAL", message, fields)

    def _log(self, level: str, message: str, fields: dict[str, Any]) -> None:
        """Internal log handler with sanitization."""
        # Sanitize message and fields
        safe_message = sanitize_text(message)
        safe_fields = sanitize_dict(fields) if fields else {}

        # Build structured record
        record = {
            "component": self.component,
            "level": level,
            "message": safe_message,
            **safe_fields,
        }

        # Log as JSON string
        log_line = json.dumps(record, ensure_ascii=False, default=str)

        # Dispatch to Python logger
        if level == "INFO":
            self._logger.info(log_line)
        elif level == "WARN":
            self._logger.warning(log_line)
        elif level == "ERROR":
            self._logger.error(log_line)
        elif level == "CRITICAL":
            self._logger.critical(log_line)
