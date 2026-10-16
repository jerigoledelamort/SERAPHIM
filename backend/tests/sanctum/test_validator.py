"""
Tests for SANCTUM validator.

Coverage:
- Validation entry point
- Error messages include file/key + fix instructions
- No credential leakage in diagnostics
"""

import tempfile
from pathlib import Path

import yaml
from seraphim.sanctum import validate_config_files


def write_config(path: Path, domain: str, data: dict):
    """Write YAML config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f)


def test_valid_config_passes():
    """Valid configuration passes validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        (root / ".seraphim").mkdir()

        result = validate_config_files(root)
        assert result.valid is True
        assert len(result.issues) == 0


def test_invalid_config_reports_issue():
    """Invalid config reports detailed issue."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        workspace_config = root / ".seraphim"
        workspace_config.mkdir()

        write_config(
            workspace_config / "runtime.yaml",
            "runtime",
            {"schema_version": 1, "unknown_field": 42},
        )

        result = validate_config_files(root)
        assert result.valid is False
        assert len(result.issues) == 1

        issue = result.issues[0]
        assert issue.severity == "error"
        assert "runtime.yaml" in issue.file
        assert "unknown_field" in issue.message.lower()
        assert len(issue.fix) > 0  # Has fix instruction


def test_malformed_yaml_reports_file_and_fix():
    """Malformed YAML reports file path and fix instruction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        workspace_config = root / ".seraphim"
        workspace_config.mkdir()

        config_file = workspace_config / "runtime.yaml"
        config_file.write_text("{ invalid yaml: [")

        result = validate_config_files(root)
        assert result.valid is False
        assert len(result.issues) == 1

        issue = result.issues[0]
        assert "runtime.yaml" in issue.file
        assert "parse" in issue.message.lower() or "yaml" in issue.message.lower()
        assert "syntax" in issue.fix.lower() or "schema" in issue.fix.lower()


def test_credential_redaction_in_diagnostics():
    """Credentials are redacted in diagnostic output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        workspace_config = root / ".seraphim"
        workspace_config.mkdir()

        # Create config with API key in unknown field
        write_config(
            workspace_config / "providers.yaml",
            "providers",
            {
                "schema_version": 1,
                "api_key": "sk-ant-1234567890abcdef",  # This is unknown field
            },
        )

        result = validate_config_files(root)
        assert result.valid is False

        # Serialize to dict (triggers sanitization)
        result_dict = result.to_dict()

        # Check that API key is redacted
        result_str = str(result_dict)
        assert "sk-ant-1234567890abcdef" not in result_str
        assert "[REDACTED]" in result_str or "redacted" in result_str.lower()


def test_duplicate_id_reports_specific_id():
    """Duplicate ID error reports the specific duplicate ID."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        workspace_config = root / ".seraphim"
        workspace_config.mkdir()

        write_config(
            workspace_config / "providers.yaml",
            "providers",
            {
                "schema_version": 1,
                "models": [
                    {"id": "duplicate_model", "provider": "anthropic", "model_name": "claude"},
                    {"id": "duplicate_model", "provider": "openai", "model_name": "gpt4"},
                ],
            },
        )

        result = validate_config_files(root)
        assert result.valid is False
        assert len(result.issues) == 1

        issue = result.issues[0]
        assert "duplicate" in issue.message.lower()
        assert "duplicate_model" in issue.message or "duplicate_model" in str(issue.details)
        assert "remove" in issue.fix.lower() or "rename" in issue.fix.lower()


def test_protected_field_conflict_reports_field_name():
    """Protected field conflict reports the specific protected field.

    DEFECT-002: the validator runs through the same ``load_config`` entry point,
    so a workspace layer trying to weaken a protected field surfaces as an error
    issue that names the field, instead of a silently valid configuration.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        system_config = root / "config"
        system_config.mkdir()
        write_config(
            system_config / "permissions.yaml",
            "permissions",
            {"schema_version": 1, "allow_external_writes": False},
        )

        workspace_config = root / ".seraphim"
        workspace_config.mkdir()
        write_config(
            workspace_config / "permissions.yaml",
            "permissions",
            {"schema_version": 1, "allow_external_writes": True},
        )

        result = validate_config_files(root)

        assert result.valid is False
        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.severity == "error"
        # The protected field is identified, not just reported as a generic error.
        assert "allow_external_writes" in issue.message
        assert "allow_external_writes" in issue.fix


def test_serialization_preserves_structure():
    """Validation result serialization preserves structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        (root / ".seraphim").mkdir()

        result = validate_config_files(root)
        result_dict = result.to_dict()

        assert "valid" in result_dict
        assert "issues" in result_dict
        assert isinstance(result_dict["issues"], list)
