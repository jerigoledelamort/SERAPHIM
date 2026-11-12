# S05 — transactional, idempotent schema migrations.

from __future__ import annotations

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.storage import Database, MigrationRunner
from seraphim.storage.migrations.base import Migration
from seraphim.storage.migrations.runner import MIGRATIONS


def test_v6_upgrade_preserves_data_and_is_idempotent(tmp_path):
    db = Database.open(tmp_path / 'legacy', environ={})
    MigrationRunner(db, MIGRATIONS[:6]).run()
    db.execute("INSERT INTO events(id,timestamp,type,component,task_id,session_id,payload_json) VALUES(?,?,?,?,?,?,?)", ('legacy-event', '2026-11-12T00:00:00.000Z', 'Legacy', 'test', '', '', '{}'))
    db.insert_row('tasks', {'id': 'legacy-task', 'goal': 'legacy', 'mode': 'EXECUTE_WITH_APPROVAL', 'status': 'NEEDS_APPROVAL', 'plan_json': '{}', 'created_at': '2026-11-12T00:00:00.000Z', 'updated_at': '2026-11-12T00:00:00.000Z'})
    db.insert_row('approvals', {'id': 'legacy-approval', 'task_id': 'legacy-task', 'step_id': 'step', 'tool_id': 'tool.fs.write_file', 'fingerprint': 'old', 'explanation': 'legacy', 'preview_json': '{}', 'resource': 'a.txt', 'risk': 'medium', 'status': 'PENDING', 'created_at': '2026-11-12T00:00:00.000Z', 'expires_at': '2026-11-12T01:00:00.000Z'})
    db.execute('INSERT INTO verification_evidence VALUES(?,?,?,?,?,?)', ('legacy-evidence', 'legacy-task', 'step', 'filesystem.stat', '2026-11-12T00:00:00.000Z', '{}'))
    db.execute('INSERT INTO verification_runs VALUES(?,?,?,?,?,?)', ('legacy-run', 'legacy-task', 'step', '2026-11-12T00:00:00.000Z', '[]', '{}'))
    db.execute('INSERT INTO execution_state(task_id,state_json,updated_at) VALUES(?,?,?)', ('legacy-task', '{}', '2026-11-12T00:00:00.000Z'))
    before = {table: db.query('SELECT * FROM ' + table) for table in db.table_names()}
    report = MigrationRunner(db).run()
    assert report.version_before == 6 and report.version_after == 7
    for table, rows in before.items():
        if table not in ('schema_meta', 'schema_migrations'):
            after = db.query('SELECT * FROM ' + table)
            assert [{key: row[key] for key in old} for row, old in zip(after, rows, strict=True)] == rows
    task = db.query_one('SELECT * FROM tasks WHERE id=?', ('legacy-task',))
    assert task['managed_verification'] == 1 and not task['authority_json']
    assert db.query('SELECT * FROM verification_authorizations') == []
    assert not db.query_one('SELECT * FROM approvals WHERE id=?', ('legacy-approval',))['authority_digest']
    assert MigrationRunner(db).run().applied == ()


def test_migration_failure_rolls_back_schema_and_bookkeeping(tmp_path):
    db = Database.open(tmp_path / 'rollback', environ={})
    MigrationRunner(db, MIGRATIONS[:6]).run()
    broken = Migration(version=7, name='broken', description='test', expected_tables=(), statements=(
        'ALTER TABLE tasks ADD COLUMN should_rollback TEXT', 'NOT VALID SQL'))
    with pytest.raises(SeraphimError):
        MigrationRunner(db, (*MIGRATIONS[:6], broken)).run()
    assert 'should_rollback' not in [r['name'] for r in db.query('PRAGMA table_info(tasks)')]
    assert MigrationRunner(db, MIGRATIONS[:6]).status().current_version == 6


