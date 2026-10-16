"""
SANCTUM validator — single entry point for config validation.

Provides:
- validate_config_files(root) → ValidationResult with detailed diagnostics
- All error messages include file path, specific key, and fix instructions
- Diagnostic output redacts credentials (API keys, tokens, passwords)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_dict, sanitize_text
from seraphim.sanctum.loader import load_config

COMPONENT = "sanctum.validator"


@dataclass
class ValidationIssue:
    """Single validation issue with location and fix instructions."""

    severity: str  # "error", "warning"
    file: str
    key: str
    message: str
    fix: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize with credential sanitization."""
        return sanitize_dict(
            {
                "severity": self.severity,
                "file": self.file,
                "key": self.key,
                "message": self.message,
                "fix": self.fix,
                "details": self.details,
            }
        )


@dataclass
class ValidationResult:
    """Result of configuration validation."""

    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize with credential sanitization."""
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_config_files(root: Path) -> ValidationResult:
    """
    Validate all configuration files in root directory.

    This is the single validation entry point for both CLI and GUI.

    Args:
        root: SERAPHIM root directory

    Returns:
        ValidationResult with all issues found (empty if valid)
    """
    issues: list[ValidationIssue] = []

    try:
        # Attempt to load all config domains with priority merging
        load_config(root)
    except SeraphimError as exc:
        # Convert SeraphimError to ValidationIssue
        details = exc.sanitized_details or {}
        file_path = details.get("file", "unknown")
        key = details.get("field") or details.get("unknown_keys", [""])[0] if "unknown_keys" in details else ""

        # Generate fix instruction based on error code
        fix_instruction = _generate_fix_instruction(exc.code, details)

        issues.append(
            ValidationIssue(
                severity="error",
                file=file_path,
                key=key,
                message=exc.safe_message,
                fix=fix_instruction,
                details=sanitize_dict(details),
            )
        )
    except Exception as exc:
        # Unexpected error (should not happen with proper error handling in loader).
        # The message is sanitized: an exception from YAML parsing can quote the
        # offending scalar, which is exactly where a pasted key would appear.
        issues.append(
            ValidationIssue(
                severity="error",
                file="unknown",
                key="",
                message=f"Unexpected validation error: {sanitize_text(str(exc))}",
                fix="Check configuration files for syntax errors",
                details={},
            )
        )

    return ValidationResult(valid=len(issues) == 0, issues=issues)


def _generate_fix_instruction(error_code: str, details: dict[str, Any]) -> str:
    """Generate fix instruction based on error code and details."""
    if error_code == ErrorCode.CONFIG_FILE_NOT_FOUND:
        return f"Create missing config file: {details.get('file', 'unknown')}"

    if error_code == ErrorCode.CONFIG_SCHEMA_INVALID:
        if "unknown_keys" in details:
            unknown = ", ".join(details["unknown_keys"])
            return f"Remove unknown keys: {unknown}. Check schema version compatibility."
        if "duplicate_id" in details:
            return f"Remove or rename duplicate ID: {details.get('duplicate_id')}"
        return "Fix YAML syntax or ensure config matches schema"

    if error_code == ErrorCode.CONFIG_CONFLICT_DETECTED:
        field = details.get("field", "unknown")
        return f"Remove override for protected field '{field}' (controlled by system security)"

    if error_code == ErrorCode.SECRET_ACCESS_DENIED:
        return "Check credential references and permission settings"

    return "Review error details and consult documentation"
