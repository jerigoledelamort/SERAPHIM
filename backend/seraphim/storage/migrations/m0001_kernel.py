# SERAPHIM storage — migration 0001: kernel tables (S05).
#
# Scope is deliberately minimal (spec §6.2: "Это целевая карта, a не требование
# создать все таблицы в нулевой миграции").  Only what the first vertical
# scenarios need is created here:
#
#   schema_meta  — schema metadata (versions, dialect, installation identity)
#   sessions     — dialog/task sessions
#   tasks        — task state (CORE-owned, spec §4.1)
#   events       — OBSERVATORY event/audit log (spec §4.16)
#   components   — REGISTRY component metadata (CONTRACTS.md §2.21)
#
# ``schema_migrations`` itself is created by the runner bootstrap because it
# must exist before the first migration can be recorded.
#
# State values are intentionally NOT constrained by CHECK here: the task/step
# state machines are owned by CONTRACTS/CORE (S16) and evolve faster than the
# immutable, checksummed SQL text below.

from __future__ import annotations

from seraphim.storage.migrations.base import Migration

MIGRATION_0001 = Migration(
    version=1,
    name="kernel_tables",
    description="Schema metadata, sessions, tasks, events/audit and component registry metadata.",
    expected_tables=(
        "schema_meta",
        "sessions",
        "tasks",
        "events",
        "components",
    ),
    statements=(
        """
        CREATE TABLE schema_meta (
            id                    INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version        INTEGER NOT NULL,
            min_supported_version INTEGER NOT NULL,
            dialect               TEXT    NOT NULL,
            installation_id       TEXT    NOT NULL,
            created_at            TEXT    NOT NULL,
            updated_at            TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE sessions (
            id             TEXT PRIMARY KEY,
            title          TEXT    NOT NULL DEFAULT '',
            status         TEXT    NOT NULL DEFAULT 'ACTIVE',
            created_at     TEXT    NOT NULL,
            updated_at     TEXT    NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE tasks (
            id             TEXT PRIMARY KEY,
            session_id     TEXT,
            goal           TEXT    NOT NULL,
            mode           TEXT    NOT NULL DEFAULT '',
            status         TEXT    NOT NULL,
            plan_json      TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL,
            updated_at     TEXT    NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX ix_tasks_status ON tasks (status)",
        "CREATE INDEX ix_tasks_session_id ON tasks (session_id)",
        """
        CREATE TABLE events (
            id             TEXT PRIMARY KEY,
            timestamp      TEXT    NOT NULL,
            type           TEXT    NOT NULL,
            component      TEXT    NOT NULL,
            severity       TEXT    NOT NULL DEFAULT 'INFO',
            task_id        TEXT    NOT NULL DEFAULT '',
            session_id     TEXT    NOT NULL DEFAULT '',
            correlation_id TEXT    NOT NULL DEFAULT '',
            payload_json   TEXT    NOT NULL DEFAULT '{}',
            schema_version INTEGER NOT NULL DEFAULT 1
        )
        """,
        "CREATE INDEX ix_events_timestamp ON events (timestamp)",
        "CREATE INDEX ix_events_task_id ON events (task_id)",
        "CREATE INDEX ix_events_type ON events (type)",
        """
        CREATE TABLE components (
            id                TEXT PRIMARY KEY,
            kind              TEXT    NOT NULL,
            name              TEXT    NOT NULL,
            version           TEXT    NOT NULL DEFAULT '',
            status            TEXT    NOT NULL DEFAULT 'REGISTERED',
            source            TEXT    NOT NULL DEFAULT '',
            license           TEXT    NOT NULL DEFAULT '',
            compatibility     TEXT    NOT NULL DEFAULT '',
            provenance_json   TEXT    NOT NULL DEFAULT '{}',
            registered_at     TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            schema_version    INTEGER NOT NULL DEFAULT 1
        )
        """,
        "CREATE UNIQUE INDEX ux_components_kind_name ON components (kind, name)",
        "CREATE INDEX ix_components_kind ON components (kind)",
    ),
)
