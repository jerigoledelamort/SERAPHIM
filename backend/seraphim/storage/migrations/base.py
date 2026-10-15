# SERAPHIM storage — migration primitives (S05).
#
# A migration is *immutable, versioned SQL text*.  Its checksum is computed from
# the text, so editing an already-applied migration is detected on the next run
# instead of silently diverging from the database (ADR-007).
#
# Statements are stored as a tuple of single statements — never one script —
# because ``sqlite3.executescript`` issues an implicit COMMIT and would break
# the all-or-nothing guarantee for a failing migration.

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from seraphim.contracts.errors import ErrorCode, SeraphimError

COMPONENT = "storage.migrations"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Migration:
    """One forward-only schema step."""

    version: int
    name: str
    statements: tuple[str, ...]
    #: Tables that must exist after the statements run (postcondition check).
    expected_tables: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise self._error("Migration version must be an integer.")
        if self.version < 1:
            raise self._error("Migration version must be >= 1.")
        if not isinstance(self.name, str) or not _NAME_RE.match(self.name):
            raise self._error("Migration name must match ^[a-z][a-z0-9_]*$.")
        if not isinstance(self.statements, tuple) or not self.statements:
            raise self._error("Migration must carry at least one statement.")
        for statement in self.statements:
            if not isinstance(statement, str) or not statement.strip():
                raise self._error("Migration statements must be non-empty strings.")
            if ";" in statement.strip().rstrip(";"):
                raise self._error(
                    "Migration statements must not contain ';': one statement per entry."
                )
        if self.expected_tables and not isinstance(self.expected_tables, tuple):
            raise self._error("expected_tables must be a tuple of table names.")

    @staticmethod
    def _error(message: str) -> SeraphimError:
        return SeraphimError(
            code=ErrorCode.MIGRATION_SEQUENCE_INVALID,
            component=COMPONENT,
            safe_message=message,
            user_action_required=True,
        )

    def checksum(self) -> str:
        """Stable SHA-256 over version, name and statement text."""
        payload = "\n".join((str(self.version), self.name, *self.statements))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "checksum": self.checksum(),
            "expected_tables": list(self.expected_tables),
        }


@dataclass(frozen=True)
class AppliedMigration:
    """A migration row already recorded in ``schema_migrations``."""

    version: int
    name: str
    applied_at: str
    checksum: str

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "name": self.name,
            "applied_at": self.applied_at,
            "checksum": self.checksum,
        }
