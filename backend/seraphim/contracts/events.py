# SERAPHIM contracts — event metadata (S04).
# Format per spec §4.16, §14.3 and CONTRACTS.md §8.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from seraphim.contracts.constants import SEVERITY_LEVELS
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id, validate_id
from seraphim.contracts.sanitization import sanitize_dict
from seraphim.contracts.timestamps import now_utc, validate_timestamp

# Event type: <domain>.<object>[.<action>] — lowercase, 2 or 3 dot-separated parts.
_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,2}$")


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def validate_event_type(event_type: str) -> str:
    """Validate event type format. Returns *event_type* if valid, raises otherwise."""
    if not isinstance(event_type, str):
        msg = f"Event type must be a string, got {type(event_type).__name__}"
        raise TypeError(msg)
    if not _EVENT_TYPE_RE.match(event_type):
        msg = (
            f"Invalid event type: {event_type!r}. "
            f"Expected '<domain>.<object>[.<action>]' (lowercase, 2-3 parts)."
        )
        raise ValueError(msg)
    return event_type


@dataclass
class Event:
    """Structured event per spec §4.16 / CONTRACTS.md §8.

    ``payload`` is sanitized at construction time to prevent secret leakage.
    """

    type: str
    component: str
    severity: str = "INFO"
    id: str = ""
    timestamp: str = ""
    task_id: str = ""
    session_id: str = ""
    correlation_id: str = ""
    schema_version: int = 1
    payload: dict[str, Any] = field(default_factory=dict)

    SCHEMA_VERSION = 1

    def __post_init__(self) -> None:
        if not self.id:
            self.id = generate_id("event")
        else:
            validate_id(self.id)
        if not self.timestamp:
            self.timestamp = now_utc()
        else:
            validate_timestamp(self.timestamp)
        validate_event_type(self.type)
        if self.severity not in SEVERITY_LEVELS:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.events",
                safe_message=(
                    f"Invalid severity: {self.severity!r}. Must be one of {SEVERITY_LEVELS}"
                ),
            )
        if not self.component:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.events",
                safe_message="Event component must not be empty",
            )
        # Sanitize payload at construction to prevent secret leakage (TB-7).
        if self.payload:
            self.payload = sanitize_dict(self.payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type,
            "component": self.component,
            "severity": self.severity,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", ""),
            type=data["type"],
            component=data["component"],
            severity=data.get("severity", "INFO"),
            task_id=data.get("task_id", ""),
            session_id=data.get("session_id", ""),
            correlation_id=data.get("correlation_id", ""),
            schema_version=data.get("schema_version", 1),
            payload=data.get("payload", {}),
        )
