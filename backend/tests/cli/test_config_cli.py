# SERAPHIM CLI — config show / config validate tests (S07 + S10).
#
# Covers the new S10 surface: ``config show`` (human + JSON, no secrets) and
# ``config validate --json`` (machine-readable, exit codes, no credential leak).

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("click")
from click.testing import CliRunner
from seraphim.cli.main import cli

MARKER_SECRET = "sk-ant-CONFIGTESTVALUE0123456789"


class TestConfigShow:
    def test_show_exits_zero(self, s10_root: Path) -> None:
        result = CliRunner().invoke(cli, ["config", "show", "--config-dir", str(s10_root)])
        assert result.exit_code == 0, result.output
        assert "Resolved configuration" in result.output
        assert "privacy:" in result.output

    def test_show_json_has_all_domains(self, s10_root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["config", "show", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert set(payload) == {
            "runtime", "providers", "routing", "mcp",
            "permissions", "privacy", "paths", "ui",
        }
        # Defaults are the single source of truth when no files are present.
        assert payload["privacy"]["redact_credentials"] is True
        assert payload["permissions"]["allow_external_writes"] is False

    def test_show_broken_config_exits_one(self, s10_root: Path) -> None:
        (s10_root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\nnot_a_real_field: boom\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["config", "show", "--config-dir", str(s10_root)])
        assert result.exit_code == 1
        assert "CONFIG_SCHEMA_INVALID" in result.output

    def test_show_missing_config_dir_is_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["config", "show", "--config-dir", str(tmp_path / "nope")]
        )
        assert result.exit_code == 2


class TestConfigValidateJson:
    def test_valid_json_output(self, s10_root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["config", "validate", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["valid"] is True
        assert payload["issues"] == []

    def test_invalid_json_output_and_exit_code(self, s10_root: Path) -> None:
        (s10_root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\nnot_a_real_field: boom\n", encoding="utf-8"
        )
        result = CliRunner().invoke(
            cli, ["config", "validate", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["valid"] is False
        assert len(payload["issues"]) >= 1
        assert payload["issues"][0]["severity"] == "error"

    def test_invalid_human_output(self, s10_root: Path) -> None:
        (s10_root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\nnot_a_real_field: boom\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["config", "validate", "--config-dir", str(s10_root)])
        assert result.exit_code == 1
        assert "Configuration validation failed" in result.output
        assert "[ERROR]" in result.output

    def test_validate_json_does_not_leak_secret(self, s10_root: Path) -> None:
        # A pasted key in an unknown field must not appear in machine output.
        (s10_root / "config" / "runtime.yaml").write_text(
            f"schema_version: 1\nnote: '{MARKER_SECRET}'\n", encoding="utf-8"
        )
        result = CliRunner().invoke(
            cli, ["config", "validate", "--config-dir", str(s10_root), "--json"]
        )
        assert result.exit_code == 1
        assert MARKER_SECRET not in result.output
