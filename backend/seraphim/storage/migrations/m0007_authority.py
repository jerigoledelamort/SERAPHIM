from seraphim.storage.migrations.base import Migration

MIGRATION_0007 = Migration(
    version=7, name="authority", description="Durable execution authority and single-use authoritative verification.",
    expected_tables=("verification_authorizations",),
    statements=(
        "ALTER TABLE tasks ADD COLUMN managed_verification INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN authority_json TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE execution_dispatches ADD COLUMN authority_json TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE approvals ADD COLUMN authority_digest TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE verification_authorizations (run_id TEXT PRIMARY KEY REFERENCES verification_runs(id), task_id TEXT NOT NULL REFERENCES tasks(id), target TEXT NOT NULL, revision INTEGER NOT NULL, authority_json TEXT NOT NULL, history_json TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0)",
        "UPDATE tasks SET managed_verification=1 WHERE id IN (SELECT task_id FROM execution_state UNION SELECT task_id FROM execution_dispatches)",
    ),
)
