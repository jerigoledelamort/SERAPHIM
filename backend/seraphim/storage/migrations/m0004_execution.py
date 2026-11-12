"""S24 durable execution state and WINGS-to-ledger operation mapping."""
from seraphim.storage.migrations.base import Migration

MIGRATION_0004 = Migration(
    version=4,
    name="execution",
    description="Durable execution state and exact dispatch intents/results.",
    expected_tables=("execution_state", "execution_dispatches"),
    statements=(
        """CREATE TABLE execution_state (
            task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            state_json TEXT NOT NULL DEFAULT '{}',
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE execution_dispatches (
            call_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            provider_call_id TEXT,
            ledger_call_id TEXT UNIQUE REFERENCES tool_calls(id),
            call_json TEXT NOT NULL,
            result_json TEXT,
            status TEXT NOT NULL,
            approval_id TEXT NOT NULL DEFAULT '',
            data_sensitivity TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT ''
        )""",
        "CREATE UNIQUE INDEX ix_execution_one_open ON execution_dispatches(task_id) WHERE status IN ('RESERVED', 'WAITING', 'STARTED', 'UNKNOWN')",
        "CREATE INDEX ix_execution_dispatch_task ON execution_dispatches(task_id, created_at)",
    ),
)
