"""Tests for SANCTUM identity loader (S08).

Coverage:
- predictable defaults for missing and empty identity files
- identity.yaml profile settings and validation
- layered priority (defaults < project < user)
- independent UI language vs model response language
- logical (machine-independent) source labels
"""

from __future__ import annotations

from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum.identity import (
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_PERSONALITY,
    DEFAULT_RESPONSE_STYLE,
    DEFAULT_SYSTEM_INSTRUCTIONS,
    IdentityConfig,
    ProfileSettings,
    load_identity,
)


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Hermetic user/workspace identity dirs that do not exist."""
    return tmp_path / "user-identity", tmp_path / "workspace-identity"


def _load(root: Path, tmp_path: Path):
    user, workspace = _dirs(tmp_path)
    return load_identity(root, user_identity_dir=user, workspace_identity_dir=workspace)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_defaults_when_no_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    identity = _load(root, tmp_path)

    assert identity.system_instructions == DEFAULT_SYSTEM_INSTRUCTIONS
    assert identity.personality == DEFAULT_PERSONALITY
    assert identity.response_style == DEFAULT_RESPONSE_STYLE
    assert identity.profile.ui_language == DEFAULT_LANGUAGE_CODE
    assert identity.profile.response_language == DEFAULT_LANGUAGE_CODE
    assert identity.sources["system_instructions"].startswith("builtin")
    assert identity.sources["personality"].startswith("builtin")
    assert identity.sources["response_style"].startswith("builtin")
    assert identity.sources["profile"] == "builtin"


def test_empty_files_use_defaults(tmp_path):
    root = tmp_path / "root"
    (root / "identity").mkdir(parents=True)
    # Empty (whitespace-only) files must fall through to predictable defaults.
    _write(root / "identity" / "system_prompt.md", "   \n\n")
    _write(root / "identity" / "personality.md", "")
    _write(root / "identity" / "response_style.md", "\t")
    _write(root / "identity" / "identity.yaml", "")

    identity = _load(root, tmp_path)
    assert identity.system_instructions == DEFAULT_SYSTEM_INSTRUCTIONS
    assert identity.personality == DEFAULT_PERSONALITY
    assert identity.response_style == DEFAULT_RESPONSE_STYLE
    assert identity.profile.ui_language == DEFAULT_LANGUAGE_CODE


def test_identity_files_loaded_with_logical_sources(tmp_path):
    root = tmp_path / "root"
    _write(root / "identity" / "system_prompt.md", "Be terse.")
    _write(root / "identity" / "personality.md", "Stern.")
    _write(root / "identity" / "response_style.md", "Bullet points.")
    _write(root / "identity" / "identity.yaml", "schema_version: 1\nprofile:\n  display_name: Ada\n")

    identity = _load(root, tmp_path)
    assert identity.system_instructions.strip() == "Be terse."
    assert identity.personality.strip() == "Stern."
    assert identity.response_style.strip() == "Bullet points."
    assert identity.profile.display_name == "Ada"

    # Sources are logical labels, never absolute machine paths.
    for source in identity.sources.values():
        assert str(tmp_path) not in source
        assert ":\\" not in source and ":/" not in source


def test_user_overrides_workspace_for_text_layers(tmp_path):
    root = tmp_path / "root"
    _write(root / "identity" / "personality.md", "base personality")
    user, workspace = _dirs(tmp_path)
    _write(workspace / "personality.md", "workspace personality")
    _write(user / "personality.md", "user personality")

    identity = load_identity(root, user_identity_dir=user, workspace_identity_dir=workspace)
    assert identity.personality.strip() == "user personality"
    assert identity.sources["personality"].startswith("~/.config/seraphim/identity/")


def test_workspace_overrides_base(tmp_path):
    root = tmp_path / "root"
    _write(root / "identity" / "response_style.md", "base style")
    user, workspace = _dirs(tmp_path)
    _write(workspace / "response_style.md", "workspace style")

    identity = load_identity(root, user_identity_dir=user, workspace_identity_dir=workspace)
    assert identity.response_style.strip() == "workspace style"


def test_identity_yaml_profile_merges_user_over_workspace(tmp_path):
    root = tmp_path / "root"
    _write(
        root / "identity" / "identity.yaml",
        "schema_version: 1\nprofile:\n  ui_language: en\n  display_name: base\n",
    )
    user, workspace = _dirs(tmp_path)
    _write(workspace / "identity.yaml", "schema_version: 1\nprofile:\n  display_name: ws\n")
    _write(user / "identity.yaml", "schema_version: 1\nprofile:\n  display_name: user\n")

    identity = load_identity(root, user_identity_dir=user, workspace_identity_dir=workspace)
    assert identity.profile.display_name == "user"
    # Field-level merge: ui_language still comes from the base file.
    assert identity.profile.ui_language == "en"


def test_unknown_identity_key_rejected(tmp_path):
    root = tmp_path / "root"
    _write(root / "identity" / "identity.yaml", "schema_version: 1\nbogus: 1\n")

    with pytest.raises(SeraphimError) as exc:
        _load(root, tmp_path)
    assert exc.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "bogus" in exc.value.safe_message


def test_unknown_profile_key_rejected(tmp_path):
    root = tmp_path / "root"
    _write(
        root / "identity" / "identity.yaml",
        "schema_version: 1\nprofile:\n  nope: 1\n",
    )

    with pytest.raises(SeraphimError) as exc:
        _load(root, tmp_path)
    assert exc.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "nope" in exc.value.safe_message


def test_invalid_language_rejected(tmp_path):
    root = tmp_path / "root"
    _write(
        root / "identity" / "identity.yaml",
        "schema_version: 1\nprofile:\n  ui_language: 'not a code!'\n",
    )
    with pytest.raises(SeraphimError) as exc:
        _load(root, tmp_path)
    assert exc.value.code == ErrorCode.CONFIG_SCHEMA_INVALID


def test_invalid_task_mode_rejected(tmp_path):
    root = tmp_path / "root"
    _write(
        root / "identity" / "identity.yaml",
        "schema_version: 1\nprofile:\n  default_task_mode: turbo\n",
    )
    with pytest.raises(SeraphimError) as exc:
        _load(root, tmp_path)
    assert exc.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "default_task_mode" in exc.value.safe_message


def test_ui_and_response_language_are_independent(tmp_path):
    root = tmp_path / "root"
    _write(
        root / "identity" / "identity.yaml",
        "schema_version: 1\nprofile:\n  ui_language: de\n  response_language: ja\n",
    )
    identity = _load(root, tmp_path)
    assert identity.profile.ui_language == "de"
    assert identity.profile.response_language == "ja"
    assert identity.profile.ui_language != identity.profile.response_language


def test_identity_config_round_trip():
    config = IdentityConfig(profile=ProfileSettings(display_name="X", ui_language="fr"))
    restored = IdentityConfig.from_dict(config.to_dict())
    assert restored.profile.display_name == "X"
    assert restored.profile.ui_language == "fr"
    assert restored.schema_version == 1
