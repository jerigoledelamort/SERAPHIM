# SERAPHIM CLI — secrets and privacy command tests (S09).
#
# Acceptance: the CLI never prints a stored value, secrets can be managed
# (set/list/show/rotate/delete), an audit finds secret material, and the privacy
# summary is shown with a decision before anything would be sent.

from __future__ import annotations

import sys
from pathlib import Path

import pytest

click = pytest.importorskip("click")
from click.testing import CliRunner  # noqa: E402
from seraphim.cli.main import cli  # noqa: E402

MARKER_SECRET = "SERAPHIM_TEST_SECRET_xyz789"
LITERAL_KEY = "sk-ant-api03-abcdefghijklmnopqrstuv"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway root with an empty HOME so no real user config is read."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    root_dir = tmp_path / "seraphim-root"
    (root_dir / "config").mkdir(parents=True)
    return root_dir


def _write_privacy(root: Path, **fields) -> None:
    import yaml

    payload = {"schema_version": 1, **fields}
    (root / "config" / "privacy.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestSecretsCli:
    def test_list_reports_backend_and_no_values(self, root: Path) -> None:
        result = CliRunner().invoke(cli, ["secrets", "list", "--config-dir", str(root)])
        assert result.exit_code == 0, result.output
        assert "Secret store:" in result.output
        assert "references: 0" in result.output

    def test_set_rejects_invalid_ref(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["secrets", "set", "Bad Ref", "--stdin", "--config-dir", str(root)],
            input="value\n",
        )
        assert result.exit_code != 0
        assert "SECRET_REF_INVALID" in result.output or "reference" in result.output.lower()

    def test_no_value_option_exists(self, root: Path) -> None:
        # A --value flag would leak into shell history and process listings.
        result = CliRunner().invoke(cli, ["secrets", "set", "--help"])
        assert result.exit_code == 0
        assert "--value" not in result.output
        assert "--from-env" in result.output
        assert "--stdin" in result.output

    @windows_only
    def test_set_list_show_rotate_delete(self, root: Path) -> None:
        runner = CliRunner()
        env = {"SERAPHIM_TEST_KEY": MARKER_SECRET}

        result = runner.invoke(
            cli,
            ["secrets", "set", "provider.openai", "--from-env", "SERAPHIM_TEST_KEY",
             "--config-dir", str(root)],
            env=env,
        )
        assert result.exit_code == 0, result.output
        assert MARKER_SECRET not in result.output

        result = runner.invoke(cli, ["secrets", "list", "--config-dir", str(root)])
        assert result.exit_code == 0
        assert "provider.openai" in result.output
        assert MARKER_SECRET not in result.output

        result = runner.invoke(cli, ["secrets", "show", "provider.openai", "--config-dir", str(root)])
        assert result.exit_code == 0
        assert MARKER_SECRET not in result.output
        assert "****" in result.output

        result = runner.invoke(
            cli,
            ["secrets", "rotate", "provider.openai", "--stdin", "--config-dir", str(root)],
            input="ROTATED-VALUE-12345678\n",
        )
        assert result.exit_code == 0, result.output
        assert "ROTATED-VALUE-12345678" not in result.output

        result = runner.invoke(
            cli, ["secrets", "delete", "provider.openai", "--yes", "--config-dir", str(root)]
        )
        assert result.exit_code == 0, result.output
        assert "Deleted" in result.output

        result = runner.invoke(cli, ["secrets", "list", "--config-dir", str(root)])
        assert "references: 0" in result.output

    @windows_only
    def test_set_requires_a_value_source(self, root: Path) -> None:
        # Without --from-env/--stdin the CLI prompts; an empty stdin aborts.
        result = CliRunner().invoke(
            cli, ["secrets", "set", "provider.openai", "--stdin", "--config-dir", str(root)],
            input="\n",
        )
        assert result.exit_code != 0

    @windows_only
    def test_show_missing_ref_reports_error(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["secrets", "show", "provider.absent", "--config-dir", str(root)]
        )
        assert result.exit_code != 0
        assert "provider.absent" in result.output

    @windows_only
    def test_rotate_missing_ref_reports_error(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["secrets", "rotate", "provider.absent", "--stdin", "--config-dir", str(root)],
            input="NEW-VALUE-12345678\n",
        )
        assert result.exit_code != 0

    @windows_only
    def test_delete_missing_ref_reports_error(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["secrets", "delete", "provider.absent", "--yes", "--config-dir", str(root)]
        )
        assert result.exit_code != 0

    def test_audit_clean_root_passes(self, root: Path) -> None:
        result = CliRunner().invoke(cli, ["secrets", "audit", "--config-dir", str(root)])
        assert result.exit_code == 0, result.output
        assert "No secret material" in result.output

    def test_audit_detects_planted_secret(self, root: Path) -> None:
        (root / "config" / "runtime.yaml").write_text(
            f"schema_version: 1\nnote: '{LITERAL_KEY}'\n", encoding="utf-8"
        )
        result = CliRunner().invoke(cli, ["secrets", "audit", "--config-dir", str(root)])
        assert result.exit_code == 1
        assert "config/runtime.yaml" in result.output
        assert LITERAL_KEY not in result.output

    def test_audit_json_output(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["secrets", "audit", "--json", "--config-dir", str(root)]
        )
        assert result.exit_code == 0
        assert '"findings"' in result.output


class TestPrivacyCli:
    def test_default_policy_denies_and_shows_summary(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["privacy", "summary", "--provider", "openai", "--categories", "prompt,files",
             "--config-dir", str(root)],
        )
        assert result.exit_code == 1
        assert "Privacy summary" in result.output
        assert "openai" in result.output
        assert "prompt" in result.output
        assert "DENIED" in result.output

    def test_allowed_when_policy_enables_provider(self, root: Path) -> None:
        _write_privacy(
            root,
            allow_external_transmission=True,
            allowed_providers=["openai"],
            require_confirmation=True,
        )
        result = CliRunner().invoke(
            cli,
            ["privacy", "summary", "--provider", "openai", "--categories", "prompt",
             "--config-dir", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "ALLOWED" in result.output
        assert "must confirm" in result.output

    def test_local_provider_allowed_without_opt_in(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["privacy", "summary", "--provider", "ollama", "--categories", "prompt", "--local",
             "--config-dir", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "local" in result.output.lower()

    def test_json_output_is_machine_readable(self, root: Path) -> None:
        import json

        result = CliRunner().invoke(
            cli,
            ["privacy", "summary", "--provider", "openai", "--categories", "prompt", "--json",
             "--config-dir", str(root)],
        )
        payload = json.loads(result.output)
        assert payload["allowed"] is False
        assert payload["summary"]["provider"] == "openai"

    def test_unknown_category_is_rejected(self, root: Path) -> None:
        result = CliRunner().invoke(
            cli,
            ["privacy", "summary", "--provider", "openai", "--categories", "soul",
             "--config-dir", str(root)],
        )
        assert result.exit_code != 0
        assert "soul" in result.output
