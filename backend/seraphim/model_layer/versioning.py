# SERAPHIM MODEL LAYER — schema version handling for transmitted entities (S12).
#
# ``ModelRequest``/``ModelResponse`` are transmitted entities carrying a
# ``schema_version`` (ADR-004), so they follow CONTRACTS.md §6.1:
#   - version newer than this build  -> CONTRACT_VERSION_UNSUPPORTED (never
#     silently accept a payload whose required fields we do not understand);
#   - version older than the minimum -> CONTRACT_VERSION_UNSUPPORTED;
#   - unknown field within range     -> preserved for round-trip, ignored.

from __future__ import annotations

from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError

COMPONENT = "model_layer.versioning"


def check_schema_version(
    data: dict[str, Any], entity: str, current: int, minimum: int
) -> int:
    """Validate ``data["schema_version"]`` for *entity* and return it.

    ``minimum`` is required (no implicit default) so that a caller cannot
    accidentally skip the lower bound (S12 review MINOR F).
    """
    version = data.get("schema_version")
    if version is None:
        raise SeraphimError(
            code=ErrorCode.VALIDATION_FAILED,
            component=COMPONENT,
            safe_message=f"{entity}: 'schema_version' is required",
        )
    if not isinstance(version, int) or isinstance(version, bool):
        raise SeraphimError(
            code=ErrorCode.VALIDATION_FAILED,
            component=COMPONENT,
            safe_message=f"{entity}: schema_version must be int, got {type(version).__name__}",
        )
    if version > current:
        raise SeraphimError(
            code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
            component=COMPONENT,
            safe_message=(
                f"{entity} v{version} > supported v{current}. Unknown required fields may be present."
            ),
            user_action_required=True,
        )
    if version < minimum:
        raise SeraphimError(
            code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
            component=COMPONENT,
            safe_message=f"{entity} v{version} < min supported v{minimum}",
            user_action_required=True,
        )
    return version


def split_known(
    data: dict[str, Any], known_fields: set[str], entity: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split *data* into known kwargs and unknown (forward-compatible) fields.

    Required fields are the caller's responsibility; this only separates the
    payload so that unknown optional fields survive a round-trip.
    """
    kwargs: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in data.items():
        if key in known_fields:
            kwargs[key] = value
        else:
            extra[key] = value
    if not kwargs and not extra:  # pragma: no cover - defensive
        raise SeraphimError(
            code=ErrorCode.VALIDATION_FAILED,
            component=COMPONENT,
            safe_message=f"{entity}: empty payload",
        )
    return kwargs, extra


def require(data: dict[str, Any], key: str, entity: str) -> Any:
    """Return ``data[key]`` or raise a normalized error instead of KeyError."""
    if key not in data:
        raise SeraphimError(
            code=ErrorCode.VALIDATION_FAILED,
            component=COMPONENT,
            safe_message=f"{entity}: required field {key!r} is missing",
        )
    return data[key]


def require_mapping(value: Any, name: str, entity: str) -> dict[str, Any]:
    """Return *value* if it is a mapping, else raise a normalized error.

    Prevents an ``AttributeError`` (or a crash inside the sanitizer) when an
    untrusted payload carries a non-object where an object is expected
    (S12 review MINOR H).
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SeraphimError(
            code=ErrorCode.VALIDATION_FAILED,
            component=COMPONENT,
            safe_message=f"{entity}: {name} must be an object, got {type(value).__name__}",
        )
    return value


__all__ = [
    "COMPONENT",
    "check_schema_version",
    "require",
    "require_mapping",
    "split_known",
]
