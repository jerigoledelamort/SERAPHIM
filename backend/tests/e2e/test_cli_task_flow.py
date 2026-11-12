from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

PLAN = {"goal": "write file", "steps": [{"id": "write", "title": "write file",
        "verification": ["file_exists"], "expected_outputs": ["a.txt"], "risk_hint": "write"}]}
CALL = {"id": "write-1", "name": "tool.fs.write_file", "arguments": {"path": "a.txt", "text": "verified bytes"}}


def _invoke(tmp_path, *args, turns=None, policy="allow", sandbox="sandbox"):
    script = tmp_path / "script.json"
    script.write_text(json.dumps(turns or []), encoding="utf-8")
    runner = ("import socket; "
              "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('offline network forbidden')); "
              "socket.create_connection=deny; socket.socket.connect=deny; "
              "from seraphim.cli.main import cli; cli()")
    result = subprocess.run([sys.executable, "-c", runner, "task",
                             "--root", str(tmp_path / "runtime"), "--sandbox", str(tmp_path / sandbox),
                             "--script", str(script), "--policy", policy, *args],
                            env={**os.environ, "PYTHONPATH": "backend"}, capture_output=True, text=True, timeout=25)
    assert result.returncode in (0, 1), result.stderr
    assert result.stdout, result.stderr
    return result, json.loads(result.stdout)


def _create(tmp_path):
    result, created = _invoke(tmp_path, "create", "write file", turns=[{"text": json.dumps(PLAN)}])
    assert result.returncode == 0
    return created["task_id"]


def test_subprocess_golden_persists_bytes_events_and_independent_evidence(tmp_path):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"unchanged")
    task_id = _create(tmp_path)
    result, record = _invoke(tmp_path, "run", task_id, turns=[{"tool_calls": [CALL]}, {"text": "done"}])
    assert result.returncode == 0
    assert record["task"]["status"] == "SUCCEEDED"
    assert (tmp_path / "sandbox" / "a.txt").read_bytes() == b"verified bytes"
    _, later = _invoke(tmp_path, "show", task_id)
    assert later["task"]["status"] == "SUCCEEDED"
    _, report = _invoke(tmp_path, "report", task_id)
    assert any(e["source"] == "filesystem.read" for e in report["evidence"])
    _, events = _invoke(tmp_path, "events", task_id)
    types = [event["type"] for event in events]
    assert "ToolCallStarted" in types and "VerificationResult" in types
    assert sentinel.read_bytes() == b"unchanged"


@pytest.mark.parametrize("kind", ["denied", "malformed", "timeout", "loop", "escape"])
def test_subprocess_negative_never_claims_success_or_changes_outside(tmp_path, kind):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"unchanged")
    task_id = _create(tmp_path)
    call = json.loads(json.dumps(CALL))
    turns = [{"tool_calls": [call]}, {"text": "done"}]
    if kind == "malformed":
        call["arguments"] = {"bad": "schema"}
    elif kind == "timeout":
        turns = [{"error_kind": "timeout"}]
    elif kind == "loop":
        turns = [{"tool_calls": [{**call, "id": str(i)}]} for i in range(4)]
    elif kind == "escape":
        call["arguments"]["path"] = "../outside.txt"
    result, record = _invoke(tmp_path, "run", task_id, turns=turns, policy="deny" if kind == "denied" else "allow")
    assert result.returncode == 1
    assert record["task"]["status"] != "SUCCEEDED"
    assert sentinel.read_bytes() == b"unchanged"


def test_approval_is_exact_and_persists_across_cli_restart(tmp_path):
    task_id = _create(tmp_path)
    result, pending = _invoke(tmp_path, "run", task_id, policy="ask", turns=[{"tool_calls": [CALL]}])
    assert result.returncode == 1
    assert pending["task"]["status"] == "NEEDS_APPROVAL"
    _, checkpoint = _invoke(tmp_path, "inspect", task_id)
    approval_id = checkpoint["approvals"][0]["id"]
    _, approved = _invoke(tmp_path, "approve", task_id, approval_id, policy="ask", turns=[{"text": "done"}])
    assert approved["task"]["status"] == "SUCCEEDED"
    assert (tmp_path / "sandbox" / "a.txt").read_bytes() == b"verified bytes"


def test_restart_changed_sandbox_rejects_approval_before_accounting(tmp_path):
    import sqlite3

    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"unchanged")
    task_id = _create(tmp_path)
    _invoke(tmp_path, "run", task_id, policy="ask", turns=[{"tool_calls": [CALL]}])
    _, checkpoint = _invoke(tmp_path, "inspect", task_id)
    approval_id = checkpoint["approvals"][0]["id"]
    database = tmp_path / "runtime" / "data" / "seraphim.sqlite"
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT state_json FROM execution_state WHERE task_id=?", (task_id,)).fetchone()[0]
    result, error = _invoke(tmp_path, "approve", task_id, approval_id, policy="ask", sandbox="other")
    assert result.returncode == 1 and "error" in error
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT state_json FROM execution_state WHERE task_id=?", (task_id,)).fetchone()[0] == before
        assert not connection.execute("SELECT consumed_at FROM approvals WHERE id=?", (approval_id,)).fetchone()[0]
        assert connection.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "NEEDS_APPROVAL"
    assert not (tmp_path / "sandbox" / "a.txt").exists()
    assert not (tmp_path / "other" / "a.txt").exists()
    assert sentinel.read_bytes() == b"unchanged"


def test_unavailable_verifier_blocks_even_when_model_says_done(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["steps"][0]["verification"].append("app_state")
    _, created = _invoke(tmp_path, "create", "unavailable verifier", turns=[{"text": json.dumps(plan)}])
    result, record = _invoke(tmp_path, "run", created["task_id"], turns=[{"tool_calls": [CALL]}, {"text": "done"}])
    assert result.returncode == 1
    assert record["task"]["status"] == "BLOCKED"
    _, report = _invoke(tmp_path, "report", created["task_id"])
    assert any(json.loads(run["report_json"])["checks"] for run in report["runs"])


def test_unknown_effect_cannot_resume_through_cli(tmp_path):
    import sqlite3

    task_id = _create(tmp_path)
    database = tmp_path / "runtime" / "data" / "seraphim.sqlite"
    with sqlite3.connect(database) as connection:
        step = json.loads(connection.execute("SELECT plan_json FROM tasks WHERE id=?", (task_id,)).fetchone()[0])["steps"][0]["id"]
        connection.execute("INSERT INTO tool_calls(id,task_id,step_id,operation,idempotency_key,status,started_at) VALUES(?,?,?,?,?,?,?)",
                           ("unknown-call", task_id, step, "tool.fs.write_file", "unknown", "UNKNOWN", "2026-11-12T00:00:00.000Z"))
    _, checkpoint = _invoke(tmp_path, "inspect", task_id)
    assert checkpoint["decision"] == "review"
    result, error = _invoke(tmp_path, "resume", task_id)
    assert result.returncode == 1 and "error" in error
    assert not (tmp_path / "sandbox" / "a.txt").exists()


def test_approval_denial_does_not_write(tmp_path):
    task_id = _create(tmp_path)
    _invoke(tmp_path, "run", task_id, policy="ask", turns=[{"tool_calls": [CALL]}])
    _, checkpoint = _invoke(tmp_path, "inspect", task_id)
    _, denied = _invoke(tmp_path, "deny", task_id, checkpoint["approvals"][0]["id"])
    assert denied["task"]["status"] != "SUCCEEDED"
    assert not (tmp_path / "sandbox" / "a.txt").exists()


def test_pause_restart_resume_and_cancel(tmp_path):
    task_id = _create(tmp_path)
    _, paused = _invoke(tmp_path, "pause", task_id)
    assert paused["task"]["status"] == "PAUSED"
    _, resumed = _invoke(tmp_path, "resume", task_id, turns=[{"tool_calls": [CALL]}, {"text": "done"}])
    assert resumed["task"]["status"] == "SUCCEEDED"
    second = _create(tmp_path)
    _, cancelled = _invoke(tmp_path, "cancel", second)
    assert cancelled["task"]["status"] == "CANCELLED"
