"""
Tests for SANCTUM configuration loader.

Coverage:
- Missing/malformed config files
- Unknown keys (critical)
- Duplicate IDs in models/routing/MCP
- Default values application
- Priority override behavior (System > User > Workspace > Task > Defaults)
- Non-overridable fields rejection
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum import load_config


@pytest.fixture
def temp_root():
    """Create temporary SERAPHIM root directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        (root / ".seraphim").mkdir()
        yield root


@pytest.fixture
def user_config_dir(tmp_path, monkeypatch):
    """Isolated user-level config directory (``~/.config/seraphim``).

    ``load_config`` resolves the user config path from ``Path.home()`` and
    exposes no override, so ``Path.home`` is redirected to a temporary directory
    for the duration of the test.  No real user file is read, written, backed up
    or restored; the public loader contract is unchanged.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home / ".config" / "seraphim"


def write_config(path: Path, domain: str, data: dict):
    """Write YAML config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f)


def test_load_defaults_when_no_files(temp_root):
    """Load config with all defaults when no config files exist."""
    config = load_config(temp_root)

    # Check defaults from schemas
    assert config.runtime.max_autonomous_depth == 3
    assert config.runtime.max_parallel_tools == 5
    assert config.permissions.allow_external_writes is False
    assert config.permissions.confirm_destructive is True
    assert config.privacy.redact_credentials is True
    assert config.ui.theme == "auto"


def test_workspace_config_overrides_defaults(temp_root):
    """Workspace config overrides defaults."""
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "runtime.yaml",
        "runtime",
        {"schema_version": 1, "max_autonomous_depth": 5},
    )

    config = load_config(temp_root)
    assert config.runtime.max_autonomous_depth == 5
    assert config.runtime.max_parallel_tools == 5  # Still default


def test_user_config_overrides_workspace(temp_root, user_config_dir):
    """User config overrides workspace config."""
    write_config(
        temp_root / ".seraphim" / "runtime.yaml",
        "runtime",
        {"schema_version": 1, "max_autonomous_depth": 5},
    )

    write_config(
        user_config_dir / "runtime.yaml",
        "runtime",
        {"schema_version": 1, "max_autonomous_depth": 10},
    )

    config = load_config(temp_root)
    assert config.runtime.max_autonomous_depth == 10


def test_system_security_overrides_all(temp_root):
    """System security config overrides all other levels.

    Uses a non-protected field (``allow_shell_exec``): a protected field such as
    ``allow_external_writes`` cannot be set by a workspace layer at all — see
    ``test_workspace_cannot_change_protected_field``.
    """
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "permissions.yaml",
        "permissions",
        {"schema_version": 1, "allow_shell_exec": True},
    )

    system_config = temp_root / "config"
    write_config(
        system_config / "permissions.yaml",
        "permissions",
        {"schema_version": 1, "allow_shell_exec": False},
    )

    config = load_config(temp_root)
    assert config.permissions.allow_shell_exec is False


def test_task_overrides_apply(temp_root):
    """Task overrides apply on top of other layers."""
    config = load_config(
        temp_root,
        task_overrides={"runtime": {"max_autonomous_depth": 7}},
    )
    assert config.runtime.max_autonomous_depth == 7


def test_task_overrides_cannot_change_protected_fields(temp_root):
    """Task overrides cannot change non-overridable fields."""
    system_config = temp_root / "config"
    write_config(
        system_config / "permissions.yaml",
        "permissions",
        {"schema_version": 1, "allow_external_writes": False},
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(
            temp_root,
            task_overrides={"permissions": {"allow_external_writes": True}},
        )

    assert exc_info.value.code == ErrorCode.CONFIG_CONFLICT_DETECTED
    assert "allow_external_writes" in exc_info.value.safe_message


def test_loader_system_security_beats_task_override_for_unprotected_field(temp_root):
    """DEFECT-001: system security outranks a task override.

    Spec §12.3 orders system security above task parameters.  The field used
    here (``allow_shell_exec``) is *not* in ``_NON_OVERRIDABLE_FIELDS``, so the
    system layer must still win by priority, not by the protected-field check.
    """
    system_config = temp_root / "config"
    write_config(
        system_config / "permissions.yaml",
        "permissions",
        {"schema_version": 1, "allow_shell_exec": False},
    )

    config = load_config(
        temp_root,
        task_overrides={"permissions": {"allow_shell_exec": True}},
    )

    assert config.permissions.allow_shell_exec is False


def test_workspace_cannot_change_protected_field(temp_root):
    """DEFECT-002: a workspace config cannot weaken a protected field.

    ``privacy.redact_credentials`` is non-overridable; setting it in the
    workspace layer must raise ``CONFIG_CONFLICT_DETECTED`` rather than being
    accepted silently.
    """
    write_config(
        temp_root / ".seraphim" / "privacy.yaml",
        "privacy",
        {"schema_version": 1, "redact_credentials": False},
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_CONFLICT_DETECTED
    assert "redact_credentials" in exc_info.value.safe_message


def test_user_cannot_change_protected_field(temp_root, user_config_dir):
    """DEFECT-002: a user config cannot weaken a protected field.

    ``permissions.allow_external_writes`` is non-overridable; setting it in the
    user layer must raise ``CONFIG_CONFLICT_DETECTED``.
    """
    write_config(
        user_config_dir / "permissions.yaml",
        "permissions",
        {"schema_version": 1, "allow_external_writes": True},
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_CONFLICT_DETECTED
    assert "allow_external_writes" in exc_info.value.safe_message


def test_malformed_yaml_raises_error(temp_root):
    """Malformed YAML raises CONFIG_SCHEMA_INVALID."""
    config_file = temp_root / ".seraphim" / "runtime.yaml"
    config_file.write_text("{ invalid yaml: [")

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "parse" in exc_info.value.safe_message.lower()


def test_unknown_keys_rejected(temp_root):
    """Unknown config keys are rejected."""
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "runtime.yaml",
        "runtime",
        {"schema_version": 1, "unknown_field": 42, "another_unknown": "value"},
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "unknown_field" in exc_info.value.safe_message.lower() or "another_unknown" in exc_info.value.safe_message.lower()


def test_duplicate_model_ids_rejected(temp_root):
    """Duplicate model IDs are rejected."""
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "providers.yaml",
        "providers",
        {
            "schema_version": 1,
            "models": [
                {"id": "model1", "provider": "anthropic", "model_name": "claude"},
                {"id": "model1", "provider": "openai", "model_name": "gpt4"},
            ],
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "duplicate" in exc_info.value.safe_message.lower()


# ---------------------------------------------------------------------------
# S09: credentials must not be stored in config files
# ---------------------------------------------------------------------------


def test_literal_secret_in_mcp_env_rejected(temp_root):
    """S09 review F3: a literal key in ``mcp.servers[].env`` is refused.

    ``env`` is the remaining config field that naturally carries a credential;
    it must hold a reference, not the key itself.
    """
    literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
    write_config(
        temp_root / ".seraphim" / "mcp.yaml",
        "mcp",
        {
            "schema_version": 1,
            "servers": [
                {
                    "id": "github",
                    "name": "GitHub",
                    "command": ["npx", "server-github"],
                    "env": {"GITHUB_TOKEN": literal},
                }
            ],
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.SECRET_REF_INVALID
    assert "env.GITHUB_TOKEN" in exc_info.value.safe_message
    # The value is never echoed back into the error.
    assert literal not in exc_info.value.safe_message
    assert literal not in json.dumps(exc_info.value.to_diagnostic_dict())


def test_literal_secret_in_mcp_command_rejected(temp_root):
    """A key embedded in the server command line is refused as well."""
    literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
    write_config(
        temp_root / ".seraphim" / "mcp.yaml",
        "mcp",
        {
            "schema_version": 1,
            "servers": [
                {
                    "id": "github",
                    "name": "GitHub",
                    "command": ["npx", f"--api-key={literal}"],
                }
            ],
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.SECRET_REF_INVALID
    assert literal not in exc_info.value.safe_message


def test_plain_mcp_env_is_accepted(temp_root):
    """A non-secret env value (a path, a flag) is still allowed."""
    write_config(
        temp_root / ".seraphim" / "mcp.yaml",
        "mcp",
        {
            "schema_version": 1,
            "servers": [
                {
                    "id": "fs",
                    "name": "Filesystem",
                    "command": ["npx", "server-fs"],
                    "env": {"WORKSPACE": "/tmp/work"},
                }
            ],
        },
    )

    config = load_config(temp_root)
    assert config.mcp.servers[0]["env"]["WORKSPACE"] == "/tmp/work"


def test_duplicate_routing_ids_rejected(temp_root):
    """Duplicate routing rule IDs are rejected."""
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "routing.yaml",
        "routing",
        {
            "schema_version": 1,
            "rules": [
                {"id": "rule1", "pattern": "*.py", "model_id": "model1"},
                {"id": "rule1", "pattern": "*.js", "model_id": "model2"},
            ],
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "duplicate" in exc_info.value.safe_message.lower()


def test_duplicate_mcp_server_ids_rejected(temp_root):
    """Duplicate MCP server IDs are rejected."""
    workspace_config = temp_root / ".seraphim"
    write_config(
        workspace_config / "mcp.yaml",
        "mcp",
        {
            "schema_version": 1,
            "servers": [
                {"id": "server1", "name": "Server One", "command": ["cmd1"]},
                {"id": "server1", "name": "Server Two", "command": ["cmd2"]},
            ],
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "duplicate" in exc_info.value.safe_message.lower()
