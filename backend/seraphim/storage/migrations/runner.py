# SERAPHIM storage — transactional migration runner (S05).
#
# Guarantees (ADR-007, CONTRACTS.md §6.2, S05 acceptance criteria):
#   1. Numbered, forward-only migrations applied in ascending order.
#   2. Each migration runs inside ONE explicit transaction together with its
#      bookkeeping row and the postcondition check; any failure rolls the whole
#      migration back, so a half-created schema is never observable.
#   3. Re-running is a no-op (idempotent): applied versions are read from
#      ``schema_migrations`` and only newer ones execute.
#   4. A database whose recorded state cannot be trusted (missing bookkeeping
#      table next to user tables, unknown/gapped version, edited checksum,
#      schema from a newer SERAPHIM) is refused instead of being patched blindly.
#   5. Rollback of an applied migration is out of scope: recovery is
#      backup/restore (CONTRACTS.md §6.2).

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.timestamps import now_utc
from seraphim.storage.db import Database
from seraphim.storage.migrations.base import AppliedMigration, Migration
from seraphim.storage.migrations.m0001_kernel import MIGRATION_0001

COMPONENT = "storage.migrations"

#: Bookkeeping table. Created by the runner, never by a migration.
BOOTSTRAP_TABLE = "schema_migrations"

_BOOTSTRAP_DDL = """
CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
)
"""

#: Ordered, forward-only migration registry.  New steps are appended here.
MIGRATIONS: tuple[Migration, ...] = (MIGRATION_0001,)


def _fail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    user_action_required: bool = False,
    details: dict[str, Any] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


@dataclass(frozen=True)
class MigrationReport:
    """Result of one :meth:`MigrationRunner.run` call."""

    fresh_database: bool
    version_before: int
    version_after: int
    applied: tuple[AppliedMigration, ...] = ()
    already_applied: tuple[int, ...] = ()
    schema_tables: tuple[str, ...] = field(default=(), compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fresh_database": self.fresh_database,
            "version_before": self.version_before,
            "version_after": self.version_after,
            "applied": [m.to_dict() for m in self.applied],
            "already_applied": list(self.already_applied),
            "schema_tables": list(self.schema_tables),
        }


@dataclass(frozen=True)
class SchemaStatus:
    """Read-only view of the database schema state (for doctor-style checks)."""

    exists: bool
    initialized: bool
    current_version: int
    head_version: int
    pending: tuple[int, ...]
    out_of_sync: bool
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "initialized": self.initialized,
            "current_version": self.current_version,
            "head_version": self.head_version,
            "pending": list(self.pending),
            "out_of_sync": self.out_of_sync,
            "meta": dict(self.meta),
        }


class MigrationRunner:
    """Applies :data:`MIGRATIONS` to a :class:`Database` transactionally."""

    def __init__(
        self,
        db: Database,
        migrations: Sequence[Migration] = MIGRATIONS,
    ) -> None:
        self._db = db
        self._migrations = tuple(migrations)
        self._validate_registry(self._migrations)

    # -- Registry validation --------------------------------------------------

    @staticmethod
    def _validate_registry(migrations: tuple[Migration, ...]) -> None:
        if not migrations:
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration registry is empty.",
                user_action_required=True,
            )
        versions = [m.version for m in migrations]
        if versions != sorted(versions):
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration registry must be ordered by version.",
                user_action_required=True,
            )
        if len(set(versions)) != len(versions):
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration versions must be unique.",
                user_action_required=True,
            )
        if versions[0] != 1:
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration registry must start at version 1.",
                user_action_required=True,
            )
        if versions != list(range(1, len(versions) + 1)):
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration registry has a gap in the version sequence.",
                user_action_required=True,
                details={"versions": versions},
            )
        names = [m.name for m in migrations]
        if len(set(names)) != len(names):
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "Migration names must be unique.",
                user_action_required=True,
            )

    # -- Introspection --------------------------------------------------------

    def status(self) -> SchemaStatus:
        """Inspect the database without modifying it."""
        exists = self._db.file_exists()
        if not exists:
            return SchemaStatus(
                exists=False,
                initialized=False,
                current_version=0,
                head_version=self.head_version,
                pending=tuple(m.version for m in self._migrations),
                out_of_sync=True,
                meta={},
            )
        tables = self._db.table_names()
        if BOOTSTRAP_TABLE not in tables:
            return SchemaStatus(
                exists=True,
                initialized=False,
                current_version=0,
                head_version=self.head_version,
                pending=tuple(m.version for m in self._migrations),
                out_of_sync=True,
                meta={"tables_present": sorted(tables)},
            )
        applied = self.applied()
        current = max((a.version for a in applied), default=0)
        known = {m.version for m in self._migrations}
        pending = tuple(sorted(known - {a.version for a in applied}))
        return SchemaStatus(
            exists=True,
            initialized=True,
            current_version=current,
            head_version=self.head_version,
            pending=pending,
            out_of_sync=bool(pending),
            meta=self._read_meta() or {},
        )

    @property
    def head_version(self) -> int:
        return self._migrations[-1].version

    def applied(self) -> tuple[AppliedMigration, ...]:
        rows = self._db.query(
            f"SELECT version, name, checksum, applied_at FROM {BOOTSTRAP_TABLE} ORDER BY version"
        )
        return tuple(
            AppliedMigration(
                version=int(row["version"]),
                name=str(row["name"]),
                applied_at=str(row["applied_at"]),
                checksum=str(row["checksum"]),
            )
            for row in rows
        )

    def _read_meta(self) -> dict[str, Any] | None:
        if "schema_meta" not in self._db.table_names():
            return None
        return self._db.query_one("SELECT * FROM schema_meta WHERE id = ?", (1,))

    # -- Execution ------------------------------------------------------------

    def run(self) -> MigrationReport:
        """Bring the database to :attr:`head_version`.  Idempotent."""
        tables = self._inspect()
        fresh = BOOTSTRAP_TABLE not in tables
        if fresh:
            self._bootstrap()
        applied = self.applied()
        self._validate_applied(applied)
        applied_versions = {a.version for a in applied}
        pending = [m for m in self._migrations if m.version not in applied_versions]

        version_before = max(applied_versions, default=0)
        newly_applied: list[AppliedMigration] = []
        for migration in pending:
            newly_applied.append(self._apply(migration))

        return MigrationReport(
            fresh_database=fresh,
            version_before=version_before,
            version_after=max(applied_versions | {m.version for m in newly_applied}, default=0),
            applied=tuple(newly_applied),
            already_applied=tuple(sorted(applied_versions)),
            schema_tables=tuple(sorted(self._db.table_names())),
        )

    def _inspect(self) -> set[str]:
        """Return table names, refusing to guess about an untrusted database."""
        if not self._db.file_exists():
            return set()
        tables = self._db.table_names()
        if BOOTSTRAP_TABLE not in tables and tables:
            raise _fail(
                ErrorCode.DB_INTEGRITY_FAILED,
                "Database contains tables but no schema_migrations bookkeeping table.",
                user_action_required=True,
                details={"tables_present": sorted(tables)[:20]},
            )
        return tables

    def _bootstrap(self) -> None:
        with self._db.transaction() as connection:
            connection.execute(_BOOTSTRAP_DDL)

    def _validate_applied(self, applied: tuple[AppliedMigration, ...]) -> None:
        known = {m.version: m for m in self._migrations}
        versions = sorted(a.version for a in applied)
        if versions and versions != list(range(1, len(versions) + 1)):
            raise _fail(
                ErrorCode.MIGRATION_SEQUENCE_INVALID,
                "schema_migrations contains a gap; the database state is not trustworthy.",
                user_action_required=True,
                details={"versions": versions},
            )
        for record in applied:
            if record.version > self.head_version:
                raise _fail(
                    ErrorCode.SCHEMA_VERSION_UNSUPPORTED,
                    "Database schema is newer than this SERAPHIM build.",
                    user_action_required=True,
                    details={
                        "database_version": record.version,
                        "supported_version": self.head_version,
                    },
                )
            migration = known.get(record.version)
            if migration is None:
                raise _fail(
                    ErrorCode.MIGRATION_MISSING,
                    "Applied migration is absent from the registry.",
                    user_action_required=True,
                    details={"version": record.version, "name": record.name},
                )
            if migration.checksum() != record.checksum:
                raise _fail(
                    ErrorCode.DB_INTEGRITY_FAILED,
                    "Migration text changed after it was applied (checksum mismatch).",
                    user_action_required=True,
                    details={"version": record.version, "name": record.name},
                )

    def _apply(self, migration: Migration) -> AppliedMigration:
        """Apply one migration atomically; roll everything back on any failure."""
        applied_at = now_utc()
        try:
            with self._db.transaction() as connection:
                for statement in migration.statements:
                    connection.execute(statement)
                self._verify_postconditions(connection, migration)
                connection.execute(
                    f"INSERT INTO {BOOTSTRAP_TABLE} (version, name, checksum, applied_at, description)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum(),
                        applied_at,
                        migration.description,
                    ),
                )
                self._write_meta(connection, migration.version)
                connection.execute(f"PRAGMA user_version = {int(migration.version)}")
        except SeraphimError as exc:
            raise _fail(
                ErrorCode.MIGRATION_FAILED,
                f"Migration {migration.version:04d} ({migration.name}) failed and was rolled back.",
                user_action_required=True,
                details={
                    "version": migration.version,
                    "name": migration.name,
                    "cause": exc.code,
                },
            ) from exc
        except Exception as exc:
            raise _fail(
                ErrorCode.MIGRATION_FAILED,
                f"Migration {migration.version:04d} ({migration.name}) failed and was rolled back.",
                user_action_required=True,
                details={
                    "version": migration.version,
                    "name": migration.name,
                    "cause": type(exc).__name__,
                },
            ) from exc
        return AppliedMigration(
            version=migration.version,
            name=migration.name,
            applied_at=applied_at,
            checksum=migration.checksum(),
        )

    @staticmethod
    def _verify_postconditions(connection: Any, migration: Migration) -> None:
        for table in migration.expected_tables:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
                ("table", table),
            ).fetchone()
            if row is None:
                raise _fail(
                    ErrorCode.MIGRATION_FAILED,
                    f"Migration {migration.version:04d} did not create table {table!r}.",
                    user_action_required=True,
                    details={"version": migration.version, "missing_table": table},
                )

    def _write_meta(self, connection: Any, version: int) -> None:
        """Upsert the single ``schema_meta`` row (table exists from migration 1)."""
        row = connection.execute("SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
                                 ("table", "schema_meta")).fetchone()
        if row is None:
            return
        timestamp = now_utc()
        existing = connection.execute(
            "SELECT installation_id FROM schema_meta WHERE id = ?", (1,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO schema_meta"
                " (id, schema_version, min_supported_version, dialect, installation_id,"
                "  created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, version, 1, "sqlite", f"inst_{uuid.uuid4()}", timestamp, timestamp),
            )
        else:
            connection.execute(
                "UPDATE schema_meta SET schema_version = ?, updated_at = ? WHERE id = ?",
                (version, timestamp),
            )
