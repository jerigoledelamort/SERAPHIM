# SERAPHIM CLI — status command tests (S10).
#
# Acceptance: compact machine-readable snapshot, correct exit codes, read-only.

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("click")
from click.testing import CliRunner
from seraphim.cli.main import cli


class TestStatusHealthy:
    def test_healthy_root_exits_zero(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root)])
        assert result.exit_code == 0, result.output
        assert "HEALTHY" in result.output

    def test_snapshot_shows_subsystems(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root)])
        for label in ("Python", "Configuration", "Database", "Secrets", "Identity"):
            assert label in result.output


class TestStatusBroken:
    def test_invalid_config_exits_one(self, s10_root: Path) -> None:
        (s10_root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\nnot_a_real_field: boom\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root)])
        assert result.exit_code == 1
        assert "ERRORS DETECTED" in result.output


class TestStatusJson:
    def test_json_output_is_machine_readable(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["healthy"] is True
        assert "database" in payload
        assert "config" in payload
        assert "runtime" in payload

    def test_json_reflects_errors(self, s10_root: Path) -> None:
        (s10_root / "config" / "routing.yaml").write_text(
            "schema_version: 1\nbogus: 1\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["healthy"] is False
        assert payload["config"]["valid"] is False


class TestStatusReadOnly:
    def test_status_does_not_create_the_database(self, s10_root: Path) -> None:
        db_path = s10_root / "data" / "seraphim.sqlite"
        CliRunner().invoke(cli, ["status", "--config-dir", str(s10_root)])
        assert not db_path.exists()


class TestStatusInvalidArgs:
    def test_missing_config_dir_is_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["status", "--config-dir", str(tmp_path / "nope")])
        assert result.exit_code == 2
