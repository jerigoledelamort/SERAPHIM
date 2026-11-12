# SERAPHIM storage — migration 0002: task persistence and resume (S17).
#
# Adds what CORE needs to restore a task after a process stop:
#   tasks            — revision counter (optimistic concurrency), pending targets,
#                      approval binding, terminal result, review flag and reason
#   task_steps       — mutable per-step status, attempts and verification report
#   tool_calls       — one row per external operation with an idempotency key
#   checkpoints      — small state summary per revision (no transcript)
#
# The immutable plan definition stays in tasks.plan_json; events are written to
# the existing events table with task_id as the reference.

from __future__ import annotations

from seraphim.storage.migrations.base import Migration

MIGRATION_0002 = Migration(
    version=2,
    name="task_persistence",
    description="Task revision, step rows, tool-call ledger, checkpoints and review flag.",
    expected_tables=(
        "task_steps",
        "tool_calls",
        "checkpoints",
    ),
    statements=(
        "ALTER TABLE tasks ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN pending_verification TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN pending_approval_step TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN approved_step_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN result_json TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE tasks ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0"
        " CHECK (review_required IN (0, 1))",
        "ALTER TABLE tasks ADD COLUMN review_reason TEXT NOT NULL DEFAULT ''",
        """
        CREATE TABLE task_steps (
            task_id       TEXT    NOT NULL,
            step_id       TEXT    NOT NULL,
            status        TEXT    NOT NULL,
            attempts      INTEGER NOT NULL DEFAULT 0,
            report_json   TEXT    NOT NULL DEFAULT '',
            updated_at    TEXT    NOT NULL,
            PRIMARY KEY (task_id, step_id),
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE tool_calls (
            id              TEXT PRIMARY KEY,
            task_id         TEXT    NOT NULL,
            step_id         TEXT    NOT NULL,
            operation       TEXT    NOT NULL,
            idempotency_key TEXT    NOT NULL UNIQUE,
            status          TEXT    NOT NULL,
            started_at      TEXT    NOT NULL,
            finished_at     TEXT    NOT NULL DEFAULT '',
            outcome_ref     TEXT    NOT NULL DEFAULT '',
            error_code      TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX ix_tool_calls_task_status ON tool_calls (task_id, status)",
        """
        CREATE TABLE checkpoints (
            id           TEXT PRIMARY KEY,
            task_id      TEXT    NOT NULL,
            revision     INTEGER NOT NULL,
            created_at   TEXT    NOT NULL,
            summary_json TEXT    NOT NULL DEFAULT '{}',
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE,
            UNIQUE (task_id, revision)
        )
        """,
    ),
)
