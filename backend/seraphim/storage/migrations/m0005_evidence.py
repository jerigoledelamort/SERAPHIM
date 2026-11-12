from seraphim.storage.migrations.base import Migration

MIGRATION_0005 = Migration(
    version=5, name="evidence", description="Independent observations and resolved verification reports.",
    expected_tables=("verification_evidence", "verification_runs"),
    statements=(
        "ALTER TABLE execution_dispatches ADD COLUMN manifest_json TEXT NOT NULL DEFAULT ''",
        "CREATE TABLE verification_evidence (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), step_id TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL)",
        "CREATE TABLE verification_runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), target TEXT NOT NULL, observed_at TEXT NOT NULL, requirements_json TEXT NOT NULL, report_json TEXT NOT NULL)",
        "CREATE INDEX ix_evidence_task ON verification_evidence(task_id,step_id)",
    ),
)
