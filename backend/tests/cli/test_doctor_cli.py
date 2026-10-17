# SERAPHIM CLI — doctor command tests (S10).
#
# Acceptance: diagnostics are understandable without reading code, support a
# machine-readable mode, never change state, and never print secrets.

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("click")
from click.testing import CliRunner
from seraphim.cli.main import cli

MARKER_SECRET = "sk-ant-DOCTORTESTVALUE0123456789"


def _write_invalid_config(root: Path) -> None:
    (root / "config" / "runtime.yaml").write_text(
        "schema_version: 1\nnot_a_real_field: boom\n", encoding="utf-8"
    )


class TestDoctorHealthy:
    def test_healthy_root_exits_zero(self, s10_root: Path) -> None:
        # A fresh root has only warnings (no DB, no local API) → healthy → exit 0.
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root)])
        assert result.exit_code == 0, result.output
        assert "HEALTHY" in result.output

    def test_output_is_understandable_without_code(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root)])
        # Each check has a human title and a readable status marker.
        assert "Root directory" in result.output
        assert "Configuration" in result.output
        assert "Database and migrations" in result.output
        assert "[PASS]" in result.output

    def test_doctor_does_not_create_the_database(self, s10_root: Path) -> None:
        # Read-only guarantee: the database must not be created by diagnostics.
        db_path = s10_root / "data" / "seraphim.sqlite"
        CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root)])
        assert not db_path.exists()


class TestDoctorBroken:
    def test_invalid_config_exits_one(self, s10_root: Path) -> None:
        _write_invalid_config(s10_root)
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root)])
        assert result.exit_code == 1
        assert "ERRORS DETECTED" in result.output
        assert "Configuration" in result.output

    def test_json_reports_error_status(self, s10_root: Path) -> None:
        _write_invalid_config(s10_root)
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["healthy"] is False
        assert payload["error_count"] >= 1
        ids = {check["id"] for check in payload["checks"]}
        assert "config" in ids


class TestDoctorJson:
    def test_json_output_is_machine_readable(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["healthy"] is True
        assert payload["status"] in {"ok", "degraded"}
        # Every check carries the fields a script needs to branch on.
        for check in payload["checks"]:
            assert {"id", "title", "severity", "summary"} <= set(check)
            assert check["severity"] in {"ok", "warning", "error"}

    def test_json_lists_all_expected_checks(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root), "--json"])
        payload = json.loads(result.output)
        ids = {check["id"] for check in payload["checks"]}
        assert {
            "root",
            "root_layout",
            "permissions",
            "config",
            "database",
            "secret_store",
            "identity",
            "prerequisites",
            "local_api",
        } <= ids


class TestDoctorSecretSafety:
    def test_planted_secret_is_not_printed(self, s10_root: Path) -> None:
        # A literal key pasted into a config value must never be echoed back.
        (s10_root / "config" / "runtime.yaml").write_text(
            f"schema_version: 1\nnote: '{MARKER_SECRET}'\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["doctor", "--config-dir", str(s10_root)])
        assert result.exit_code == 1  # unknown key → config error
        assert MARKER_SECRET not in result.output

        result = CliRunner().invoke(
            cli, ["doctor", "--config-dir", str(s10_root), "--json"]
        )
        assert MARKER_SECRET not in result.output


class TestDoctorInvalidArgs:
    def test_missing_config_dir_is_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["doctor", "--config-dir", str(tmp_path / "does-not-exist")]
        )
        # Click rejects a non-existent --config-dir before the command runs.
        assert result.exit_code == 2

    def test_unknown_flag_is_usage_error(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--nope"])
        assert result.exit_code == 2
