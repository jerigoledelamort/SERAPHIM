"""CLI tests for `seraphim identity show` / `prompt-preview` (S08).

The CLI is a thin wrapper over the SANCTUM loader and prompt composer, so these
tests assert structure (exit code, active layer ids, profile lines) rather than
exact full output. Skipped when `click` is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

click = pytest.importorskip("click")

from click.testing import CliRunner  # noqa: E402
from seraphim.cli.identity import identity_group  # noqa: E402


def _write_identity(root: Path) -> None:
    (root / "identity").mkdir(parents=True)
    (root / "identity" / "personality.md").write_text("Personality: terse.\n", encoding="utf-8")
    (root / "identity" / "identity.yaml").write_text(
        "schema_version: 1\nprofile:\n  ui_language: de\n  response_language: ja\n",
        encoding="utf-8",
    )


def test_identity_show_lists_layers(tmp_path):
    _write_identity(tmp_path)
    runner = CliRunner()
    result = runner.invoke(identity_group, ["show", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "system_policy" in result.output
    assert "trust=trusted" in result.output
    assert "ui_language: de" in result.output
    assert "response_language: ja" in result.output


def test_identity_show_no_content_leak(tmp_path):
    _write_identity(tmp_path)
    runner = CliRunner()
    result = runner.invoke(identity_group, ["show", "--config-dir", str(tmp_path)])
    # `show` prints layer metadata only, not the layer content.
    assert "Personality: terse." not in result.output


def test_identity_prompt_preview(tmp_path):
    _write_identity(tmp_path)
    runner = CliRunner()
    result = runner.invoke(identity_group, ["prompt-preview", "--config-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "<<<LAYER id=system_policy" in result.output
    assert "<<<LAYER id=personality" in result.output
