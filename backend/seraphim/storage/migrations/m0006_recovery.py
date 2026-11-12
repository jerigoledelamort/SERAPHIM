from seraphim.storage.migrations.base import Migration

MIGRATION_0006 = Migration(
    version=6, name="recovery", description="Exclusive execution ownership and recovery checkpoints.",
    expected_tables=("execution_owners", "recovery_checkpoints"),
    statements=(
        "CREATE TABLE execution_owners (task_id TEXT PRIMARY KEY REFERENCES tasks(id), owner TEXT NOT NULL)",
        "CREATE TABLE recovery_checkpoints (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), created_at TEXT NOT NULL, payload_json TEXT NOT NULL)",
    ),
)
