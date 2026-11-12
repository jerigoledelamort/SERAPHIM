from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from seraphim.core.evidence import CheckSpec
from seraphim.core.task_model import TaskStatus
from seraphim.core.verification import VerificationEngine
from seraphim.model_layer.fake import FakeTurn
from seraphim.wings.fs_paths import FsRoot

from tests.core.test_executor import _call, _runtime


def _executed(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()]), FakeTurn(text="done")])
    task_id = executor.create("write test file")
    executor.run(task_id)
    return executor, VerificationEngine(db, executor.registry, FsRoot(root)), task_id, root, db


def test_independent_file_evidence_is_required_for_success(tmp_path):
    executor, engine, task_id, _root, db = _executed(tmp_path)
    report = engine.verify_pending(task_id)
    assert report.status == "verified"
    assert engine.finish_task(task_id).passed
    assert executor.tasks.load(task_id).task.status is TaskStatus.SUCCEEDED
    for check in report.checks:
        assert check.source and check.observed_at
        assert db.query_one("SELECT * FROM verification_evidence WHERE id=?", (check.evidence_ref,))
    assert any(c.source == "filesystem.read" for c in report.checks)


@pytest.mark.parametrize("change", ["missing", "wrong"])
def test_fake_success_missing_or_wrong_file_never_succeeds(tmp_path, change):
    executor, engine, task_id, root, _ = _executed(tmp_path)
    if change == "missing":
        (root / "a.txt").unlink()
    else:
        (root / "a.txt").write_text("wrong")
    report = engine.verify_pending(task_id)
    assert report.status == "failed"
    assert executor.tasks.load(task_id).task.status is TaskStatus.FAILED


def test_final_verification_reobserves_mutable_output(tmp_path):
    executor, engine, task_id, root, _ = _executed(tmp_path)
    assert engine.verify_pending(task_id).passed
    (root / "a.txt").write_text("changed later")
    assert not engine.finish_task(task_id).passed
    assert executor.tasks.load(task_id).task.status is TaskStatus.FAILED


def test_all_report_statuses_and_unavailable_verifier(tmp_path):
    _executor, engine, task_id, _root, _ = _executed(tmp_path)
    assert engine.check(task_id, "checks", []).status == "unverified"
    assert engine.check(task_id, "checks", [CheckSpec("app_state")]).status == "unverified"
    assert engine.check(task_id, "checks", [CheckSpec("file_exists", "a.txt"), CheckSpec("screenshot")]).status == "partially_verified"
    assert engine.check(task_id, "checks", [CheckSpec("file_exists", "missing.txt")]).status == "failed"
    digest = hashlib.sha256(b"hello").hexdigest()
    assert engine.check(task_id, "checks", [CheckSpec("file_hash", "a.txt", digest)]).passed


def test_manifest_check_cannot_be_removed_by_plan(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()]), FakeTurn(text="done")])
    manifest = executor.registry.manifest("tool.fs.write_file")
    entry = executor.registry._entries[manifest.id]
    entry.manifest = replace(manifest, verification=("app_state",))
    task_id = executor.create("write test file")
    executor.run(task_id)
    # Editing the registry after dispatch cannot erase persisted requirements.
    entry.manifest = manifest
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    from seraphim.contracts.errors import SeraphimError
    with pytest.raises(SeraphimError):
        engine.verify_pending(task_id)
    entry.manifest = replace(manifest, verification=("app_state",))
    report = engine.verify_pending(task_id)
    assert report.status == "partially_verified"
    assert executor.tasks.load(task_id).task.status is TaskStatus.BLOCKED
    assert db.query("SELECT * FROM verification_runs WHERE task_id=?", (task_id,))


def test_path_escape_and_dangling_result_not_evidence(tmp_path):
    _, engine, task_id, _, _ = _executed(tmp_path)
    assert not engine.check(task_id, "checks", [CheckSpec("file_exists", "../external")]).passed
    assert engine.check(task_id, "checks", [CheckSpec("tool_result", call_id="not-real")]).status == "unverified"


def test_last_write_is_current_postcondition(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[
        _call(), _call(arguments={"path": "a.txt", "text": "final"}, call_id="second"),
    ]), FakeTurn(text="done")])
    task_id = executor.create("write final content")
    executor.run(task_id)
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    assert engine.verify_pending(task_id).passed
    assert engine.finish_task(task_id).passed
    assert (root / "a.txt").read_text() == "final"
    assert len(engine.store.calls(task_id)) == 2


def test_move_composes_written_content_and_source_absence(tmp_path):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[
        _call(arguments={"path": "temporary.txt", "text": "final"}),
        _call("tool.fs.move_path", {"path": "temporary.txt", "to": "a.txt"}, call_id="move"),
    ]), FakeTurn(text="done")])
    task_id = executor.create("write and move")
    executor.run(task_id)
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    assert engine.verify_pending(task_id).passed
    assert engine.finish_task(task_id).passed
    assert not (root / "temporary.txt").exists()
    assert (root / "a.txt").read_text() == "final"


def test_optional_unavailable_does_not_block_required_evidence(tmp_path):
    _executor, engine, task_id, _root, _db = _executed(tmp_path)
    report = engine.check(task_id, "checks", [CheckSpec("file_exists", "a.txt"),
                                            CheckSpec("screenshot", mandatory=False)])
    assert report.passed
    assert not report.checks[1].available


def test_forged_report_cannot_advance_executed_task(tmp_path):
    from seraphim.contracts.errors import SeraphimError
    from seraphim.contracts.timestamps import now_utc
    from seraphim.core.task_machine import Verified
    from seraphim.core.task_model import CheckOutcome, VerificationReport

    executor, _engine, task_id, _root, _db = _executed(tmp_path)
    record = executor.tasks.load(task_id)
    report = VerificationReport("forged", (CheckOutcome("fake", True, "nonexistent"),))
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(record.task.pending_verification, report),
                            event_type="Verified", at=now_utc())
    assert executor.tasks.load(task_id).task.status is TaskStatus.VERIFYING


@pytest.mark.parametrize("values", [{"kind": []}, {"kind": "file_exists", "target": 1},
                                   {"kind": "app_state", "mandatory": "false"}])
def test_malformed_check_fields_are_rejected(values):
    with pytest.raises(ValueError):
        CheckSpec(**values)


def test_nonzero_command_and_truncated_output_fail_verification(tmp_path):
    _, engine, task_id, _, db = _executed(tmp_path)
    row = engine.store.calls(task_id)[0]
    result = json.loads(row["result_json"])
    result["output"] = {"exit_code": 1, "stdout": "passed", "stdout_truncated": False}
    db.execute("UPDATE execution_dispatches SET result_json=? WHERE call_id=?", (json.dumps(result), row["call_id"]))
    assert not engine.check(task_id, "checks", [CheckSpec("command_exit", call_id=row["call_id"])]).passed
    result["output"].update(exit_code=0, stdout_truncated=True)
    db.execute("UPDATE execution_dispatches SET result_json=? WHERE call_id=?", (json.dumps(result), row["call_id"]))
    assert engine.check(task_id, "checks", [CheckSpec("test_output", expected="passed", call_id=row["call_id"])]).status == "unverified"
