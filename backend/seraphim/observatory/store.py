# SERAPHIM OBSERVATORY — event persistence (S06).
# Spec §14.3: events recorded in DB, survive restart.

from __future__ import annotations

import json
import logging
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event
from seraphim.storage.db import Database

logger = logging.getLogger(__name__)


class EventStore:
    """Persistent event storage using SQLite.

    Events table schema (from m0001_kernel):
    - id TEXT PRIMARY KEY
    - timestamp TEXT
    - type TEXT
    - component TEXT
    - severity TEXT
    - task_id TEXT
    - session_id TEXT
    - correlation_id TEXT
    - payload_json TEXT
    - schema_version INTEGER
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, event: Event) -> None:
        """Save event to database.

        Payload is serialized to JSON.
        Uses parameterized query for safety.
        """
        if not isinstance(event, Event):
            msg = f"Event must be Event instance, got {type(event).__name__}"
            raise TypeError(msg)

        payload_json = json.dumps(event.payload) if event.payload else "{}"

        try:
            self.db.execute(
                """
                INSERT INTO events (
                    id, timestamp, type, component, severity,
                    task_id, session_id, correlation_id, payload_json, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.timestamp,
                    event.type,
                    event.component,
                    event.severity,
                    event.task_id or "",
                    event.session_id or "",
                    event.correlation_id or "",
                    payload_json,
                    event.schema_version,
                ),
            )
        except Exception as exc:
            raise SeraphimError(
                code=ErrorCode.DB_UNAVAILABLE,
                component="observatory.store",
                safe_message=f"Failed to save event {event.id}: {exc}",
            ) from exc

    def load_by_id(self, event_id: str) -> Event | None:
        """Load event by ID. Returns None if not found."""
        row = self.db.query_one(
            "SELECT * FROM events WHERE id = ?",
            (event_id,),
        )
        if not row:
            return None
        return self._row_to_event(row)

    def load_by_task(self, task_id: str, limit: int = 100) -> list[Event]:
        """Load events for a given task, ordered by timestamp DESC."""
        rows = self.db.query(
            "SELECT * FROM events WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?",
            (task_id, limit),
        )
        return [self._row_to_event(row) for row in rows]

    def load_by_session(self, session_id: str, limit: int = 100) -> list[Event]:
        """Load events for a given session, ordered by timestamp DESC."""
        rows = self.db.query(
            "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        )
        return [self._row_to_event(row) for row in rows]

    def load_by_type(self, event_type: str, limit: int = 100) -> list[Event]:
        """Load events by type, ordered by timestamp DESC."""
        rows = self.db.query(
            "SELECT * FROM events WHERE type = ? ORDER BY timestamp DESC LIMIT ?",
            (event_type, limit),
        )
        return [self._row_to_event(row) for row in rows]

    def count_by_task(self, task_id: str) -> int:
        """Count events for a given task."""
        row = self.db.query_one(
            "SELECT COUNT(*) as cnt FROM events WHERE task_id = ?",
            (task_id,),
        )
        return row["cnt"] if row else 0

    def _row_to_event(self, row: dict[str, Any]) -> Event:
        """Convert database row to Event instance."""
        payload = json.loads(row["payload_json"]) if row.get("payload_json") else {}
        return Event(
            id=row["id"],
            timestamp=row["timestamp"],
            type=row["type"],
            component=row["component"],
            severity=row["severity"],
            task_id=row.get("task_id", ""),
            session_id=row.get("session_id", ""),
            correlation_id=row.get("correlation_id", ""),
            schema_version=row.get("schema_version", 1),
            payload=payload,
        )
