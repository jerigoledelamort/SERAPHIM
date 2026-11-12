# SERAPHIM storage — migration 0003: approval requests (S23).
#
# One row per request for a risky tool call. The fingerprint binds the approval to
# one exact operation (tool, arguments, task, step); it is a hash, never the raw
# arguments. Status moves PENDING -> APPROVED|DENIED|EXPIRED and APPROVED -> CONSUMED.

from __future__ import annotations

from seraphim.storage.migrations.base import Migration

MIGRATION_0003 = Migration(
    version=3,
    name="approvals",
    description="Approval requests bound to one operation fingerprint, with expiry.",
    expected_tables=("approvals",),
    statements=(
        """
        CREATE TABLE approvals (
            id           TEXT PRIMARY KEY,
            task_id      TEXT    NOT NULL,
            step_id      TEXT    NOT NULL,
            tool_id      TEXT    NOT NULL,
            fingerprint  TEXT    NOT NULL,
            explanation  TEXT    NOT NULL,
            preview_json TEXT    NOT NULL,
            resource     TEXT    NOT NULL DEFAULT '',
            risk         TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            created_at   TEXT    NOT NULL,
            expires_at   TEXT    NOT NULL,
            decided_at   TEXT    NOT NULL DEFAULT '',
            consumed_at  TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX ix_approvals_task_status ON approvals (task_id, status)",
    ),
)
