from __future__ import annotations

import json

from click.testing import CliRunner
from seraphim.cli.main import cli


def test_task_help_lists_thin_service_commands():
    result = CliRunner().invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    for name in ("create", "run", "show", "events", "report", "inspect", "approve", "deny", "pause", "resume", "cancel"):
        assert name in result.output


def test_click_create_and_list_persist_task(tmp_path):
    script = tmp_path / "plan.json"
    script.write_text(json.dumps([{"text": json.dumps({"goal": "write", "steps": [
        {"id": "write", "title": "write", "verification": ["file_exists"], "expected_outputs": ["a.txt"]}
    ]})}]), encoding="utf-8")
    args = ["task", "--root", str(tmp_path / "runtime"), "--sandbox", str(tmp_path / "sandbox"),
            "--script", str(script)]
    runner = CliRunner()
    created = runner.invoke(cli, [*args, "create", "write"])
    assert created.exit_code == 0, created.output
    task_id = json.loads(created.output)["task_id"]
    listed = runner.invoke(cli, [*args, "list"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)[0]["task"]["id"] == task_id
