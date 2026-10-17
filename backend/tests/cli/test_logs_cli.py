# SERAPHIM CLI — logs tail command tests (S10).
#
# Acceptance: reads and redacts log lines, correct exit codes, machine-readable
# output, and refuses invalid arguments.

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("click")
from click.testing import CliRunner
from seraphim.cli.main import cli

MARKER_SECRET = "SUPERSECRETVALUE99887766"


def _make_log(root: Path, name: str, content: str) -> None:
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "logs" / name).write_text(content, encoding="utf-8")


class TestLogsTail:
    def test_no_logs_exits_zero(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["logs", "tail", "--config-dir", str(s10_root)])
        assert result.exit_code == 0, result.output
        assert "No log files found" in result.output

    def test_tail_shows_lines(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", "first line\nsecond line\nthird line\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--lines", "2"]
        )
        assert result.exit_code == 0, result.output
        assert "second line" in result.output
        assert "third line" in result.output

    def test_zero_lines_exits_zero(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", "a\nb\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--lines", "0"]
        )
        assert result.exit_code == 0

    def test_json_output_is_machine_readable(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", "one\ntwo\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["selected"] == "runtime.log"
        assert isinstance(payload["lines"], list)


class TestLogsRedaction:
    def test_secret_in_log_is_redacted(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", f"connecting secret={MARKER_SECRET}\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 0
        assert MARKER_SECRET not in result.output
        assert "REDACTED" in result.output


class TestLogsErrors:
    def test_missing_file_name_exits_one(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", "x\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--file", "absent.log"]
        )
        assert result.exit_code == 1
        assert "LOG_FILE_NOT_FOUND" in result.output or "absent.log" in result.output

    def test_negative_lines_is_rejected(self, s10_root: Path) -> None:
        _make_log(s10_root, "runtime.log", "x\n")
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(s10_root), "--lines=-1"]
        )
        assert result.exit_code == 1

    def test_missing_config_dir_is_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["logs", "tail", "--config-dir", str(tmp_path / "nope")]
        )
        assert result.exit_code == 2
