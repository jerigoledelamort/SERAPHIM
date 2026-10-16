# SERAPHIM contracts — structured error envelope (S04).
# Matches spec §14.2 and CONTRACTS.md §7.
# Stack traces and secrets are NEVER included in user-facing serialization.

from __future__ import annotations

from typing import Any

from seraphim.contracts.sanitization import sanitize_dict, sanitize_text, strip_traceback


class ErrorCode:
    """Stable error code constants (UPPER_SNAKE per CONTRACTS.md §7).

    Codes are grouped by subsystem. Each code maps to a localization key
    ``errors.<code_lowercase>``.
    """

    # --- Generic / CONTRACTS layer ---
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONTRACT_VERSION_UNSUPPORTED = "CONTRACT_VERSION_UNSUPPORTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"

    # --- CORE ---
    TASK_INVALID = "TASK_INVALID"
    PLAN_VALIDATION_FAILED = "PLAN_VALIDATION_FAILED"
    RECOVERY_MAX_ATTEMPTS = "RECOVERY_MAX_ATTEMPTS"
    ANTI_LOOP_DETECTED = "ANTI_LOOP_DETECTED"
    VERIFY_TIMEOUT = "VERIFY_TIMEOUT"

    # --- SANCTUM ---
    CONFIG_FILE_NOT_FOUND = "CONFIG_FILE_NOT_FOUND"
    CONFIG_SCHEMA_INVALID = "CONFIG_SCHEMA_INVALID"
    SECRET_ACCESS_DENIED = "SECRET_ACCESS_DENIED"
    SECRET_NOT_FOUND = "SECRET_NOT_FOUND"
    SECRET_REF_INVALID = "SECRET_REF_INVALID"
    SECRET_STORE_UNAVAILABLE = "SECRET_STORE_UNAVAILABLE"
    CONFIG_CONFLICT_DETECTED = "CONFIG_CONFLICT_DETECTED"

    # --- AEGIS ---
    POLICY_EVALUATION_FAILED = "POLICY_EVALUATION_FAILED"
    UNTRUSTED_DATA_DETECTED = "UNTRUSTED_DATA_DETECTED"
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    PRIVACY_TRANSMISSION_DENIED = "PRIVACY_TRANSMISSION_DENIED"

    # --- COMPASS ---
    NO_MODEL_AVAILABLE = "NO_MODEL_AVAILABLE"
    ROUTING_TIMEOUT = "ROUTING_TIMEOUT"
    COMPASS_CONFLICT = "COMPASS_CONFLICT"

    # --- MODEL LAYER ---
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    RESPONSE_FORMAT_INVALID = "RESPONSE_FORMAT_INVALID"

    # --- MEMORY ---
    MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
    RETRIEVAL_TIMEOUT = "RETRIEVAL_TIMEOUT"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"

    # --- WINGS ---
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_SCHEMA_INVALID = "TOOL_SCHEMA_INVALID"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_CANCELLED = "TOOL_CANCELLED"
    TOOL_PERMISSION_DENIED = "TOOL_PERMISSION_DENIED"

    # --- BRIDGES ---
    INTEGRATION_TIMEOUT = "INTEGRATION_TIMEOUT"
    INTEGRATION_SCHEMA_MISMATCH = "INTEGRATION_SCHEMA_MISMATCH"
    INTEGRATION_TEST_FAILED = "INTEGRATION_TEST_FAILED"
    INTEGRATION_COMPATIBILITY_ERROR = "INTEGRATION_COMPATIBILITY_ERROR"

    # --- MCP GATEWAY ---
    MCP_CONNECTION_FAILED = "MCP_CONNECTION_FAILED"
    MCP_INVALID_SCHEMA = "MCP_INVALID_SCHEMA"
    MCP_TIMEOUT = "MCP_TIMEOUT"
    MCP_UNTRUSTED = "MCP_UNTRUSTED"

    # --- SKILLS ---
    SKILL_MANIFEST_INVALID = "SKILL_MANIFEST_INVALID"
    SKILL_DEPENDENCY_MISSING = "SKILL_DEPENDENCY_MISSING"
    SKILL_CONFLICT = "SKILL_CONFLICT"

    # --- ARCHIVE ---
    ARCHIVE_NOT_FOUND = "ARCHIVE_NOT_FOUND"
    ARCHIVE_IMPORT_FAILED = "ARCHIVE_IMPORT_FAILED"

    # --- OBSERVATORY ---
    LOG_ROTATION_FAILED = "LOG_ROTATION_FAILED"
    DIAGNOSTIC_EXPORT_FAILED = "DIAGNOSTIC_EXPORT_FAILED"
    EVENT_LOSS_DETECTED = "EVENT_LOSS_DETECTED"

    # --- FORGE ---
    ARTIFACT_WRITE_FAILED = "ARTIFACT_WRITE_FAILED"
    ARTIFACT_INTEGRITY_FAILED = "ARTIFACT_INTEGRITY_FAILED"
    ARTIFACT_ROLLBACK_FAILED = "ARTIFACT_ROLLBACK_FAILED"

    # --- EYES ---
    SCREENSHOT_FAILED = "SCREENSHOT_FAILED"
    VISUAL_COMPARISON_FAILED = "VISUAL_COMPARISON_FAILED"
    VISION_MODEL_ERROR = "VISION_MODEL_ERROR"

    # --- VOICE ---
    VOICE_INPUT_INVALID = "VOICE_INPUT_INVALID"
    VOICE_CHANNEL_UNAVAILABLE = "VOICE_CHANNEL_UNAVAILABLE"

    # --- REGISTRY ---
    REGISTRY_CONFLICT = "REGISTRY_CONFLICT"
    REGISTRY_INTEGRITY_FAILED = "REGISTRY_INTEGRITY_FAILED"

    # --- STORAGE / SQLite migrations (REGISTRY-owned, S05) ---
    DB_PATH_OUTSIDE_ROOT = "DB_PATH_OUTSIDE_ROOT"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    DB_INTEGRITY_FAILED = "DB_INTEGRITY_FAILED"
    MIGRATION_FAILED = "MIGRATION_FAILED"
    MIGRATION_SEQUENCE_INVALID = "MIGRATION_SEQUENCE_INVALID"
    MIGRATION_MISSING = "MIGRATION_MISSING"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"
    QUERY_INVALID = "QUERY_INVALID"

    # --- PULSE ---
    PULSE_AGGREGATION_FAILED = "PULSE_AGGREGATION_FAILED"

    # --- APOCRYPHA ---
    APOCRYPHA_ISOLATION_BREACH = "APOCRYPHA_ISOLATION_BREACH"
    EXPERIMENT_UNSAFE = "EXPERIMENT_UNSAFE"

    # --- LAB ---
    EVAL_TIMEOUT = "EVAL_TIMEOUT"
    EVAL_CONFIG_INVALID = "EVAL_CONFIG_INVALID"
    EVAL_RESULT_MISMATCH = "EVAL_RESULT_MISMATCH"

    # --- EXPERIENCE / INSTINCTS ---
    EXPERIENCE_CONTRADICTION = "EXPERIENCE_CONTRADICTION"
    EXPERIENCE_INVALID_PROVENANCE = "EXPERIENCE_INVALID_PROVENANCE"
    INSTINCT_INVALID_SCOPE = "INSTINCT_INVALID_SCOPE"
    INSTINCT_CONTRADICTION = "INSTINCT_CONTRADICTION"


def _code_to_message_key(code: str) -> str:
    """Derive the localization key from an error code (CONTRACTS.md §7)."""
    return f"errors.{code.lower()}"


class SeraphimError(Exception):
    """Structured error matching the §14.2 error envelope.

    User-facing fields (``to_dict``) contain **no** stack traces, secrets,
    or raw exception details.  Diagnostic fields (``to_diagnostic_dict``)
    carry sanitized details for OBSERVATORY / debugging.
    """

    def __init__(
        self,
        code: str,
        component: str,
        *,
        safe_message: str = "",
        retryable: bool = False,
        user_action_required: bool = False,
        details_ref: str = "",
        correlation_id: str = "",
        task_id: str = "",
        tool_call_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message_key = _code_to_message_key(code)
        self.component = component
        # ``safe_message`` is sanitized at construction time: an adapter must not
        # be able to leak a key value through an error message (TB-7).  It is the
        # only user-visible free-text field (see ``to_diagnostic_dict``).
        self.safe_message = sanitize_text(safe_message)
        self.retryable = retryable
        self.user_action_required = user_action_required
        self.details_ref = details_ref
        self.correlation_id = correlation_id
        self.task_id = task_id
        self.tool_call_id = tool_call_id
        # Sanitize provided details at construction time.
        self.sanitized_details: dict[str, Any] = sanitize_dict(details) if details else {}
        super().__init__(self.safe_message or code)

    # -- User-facing serialization (safe for UI/CLI) -------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize for UI/CLI consumption (§14.2). No secrets, no stack traces."""
        return {
            "code": self.code,
            "message_key": self.message_key,
            "component": self.component,
            "retryable": self.retryable,
            "user_action_required": self.user_action_required,
            "details_ref": self.details_ref,
        }

    # -- Diagnostic serialization (OBSERVATORY / developer tools) ------------

    def to_diagnostic_dict(self) -> dict[str, Any]:
        """Full diagnostic view. Still sanitized, but includes correlation IDs."""
        d = self.to_dict()
        d["safe_message"] = self.safe_message
        d["correlation_id"] = self.correlation_id
        d["task_id"] = self.task_id
        d["tool_call_id"] = self.tool_call_id
        d["sanitized_details"] = self.sanitized_details
        return d

    # -- Factory helpers -----------------------------------------------------

    @staticmethod
    def from_exception(
        exc: BaseException,
        component: str,
        *,
        correlation_id: str = "",
        task_id: str = "",
    ) -> SeraphimError:
        """Wrap an arbitrary exception into a SeraphimError.

        The raw traceback is NOT included. Only the exception class name and
        a sanitized first-line message are kept.
        """
        raw_msg = str(exc)
        safe_msg = strip_traceback(raw_msg)
        return SeraphimError(
            code=ErrorCode.INTERNAL_ERROR,
            component=component,
            safe_message=f"{type(exc).__name__}: {safe_msg}",
            retryable=False,
            correlation_id=correlation_id,
            task_id=task_id,
        )

    def __repr__(self) -> str:
        return (
            f"SeraphimError(code={self.code!r}, component={self.component!r}, "
            f"retryable={self.retryable})"
        )
