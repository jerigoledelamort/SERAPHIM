# SERAPHIM contracts — versioned entity base (S04).
# Schema version rules per CONTRACTS.md §6.1.
#
# Backward compatibility:
#   - Minor (compatible): add optional field. Consumer preserves unknown
#     optional fields for round-trip, ignores them for processing.
#   - Major (incompatible): remove/change/add required field. New version.
#   - Unknown REQUIRED field (from a future major) → CONTRACT_VERSION_UNSUPPORTED.
#   - Unknown OPTIONAL field (within supported range) → preserve + ignore.

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar

from seraphim.contracts.errors import ErrorCode, SeraphimError


class VersionedEntity:
    """Mixin for all persisted/transmitted entities that carry a schema_version.

    Subclasses **must** be ``@dataclass`` and should set the class-level
    ``SCHEMA_VERSION`` and ``MIN_SUPPORTED_VERSION``.
    """

    SCHEMA_VERSION: ClassVar[int] = 1
    MIN_SUPPORTED_VERSION: ClassVar[int] = 1

    # Instance field (declared here so dataclass field ordering is predictable
    # for subclasses that inherit from VersionedEntity as the first base).
    schema_version: int

    def __post_init__(self) -> None:
        self._validate_schema_version()

    def _validate_schema_version(self) -> None:
        cls = type(self)
        if not isinstance(self.schema_version, int):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.versioned",
                safe_message=f"schema_version must be int, got {type(self.schema_version).__name__}",
            )
        if self.schema_version < cls.MIN_SUPPORTED_VERSION:
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="contracts.versioned",
                safe_message=(
                    f"{cls.__name__} v{self.schema_version} < "
                    f"min supported v{cls.MIN_SUPPORTED_VERSION}"
                ),
                user_action_required=True,
            )
        if self.schema_version > cls.SCHEMA_VERSION:
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="contracts.versioned",
                safe_message=(
                    f"{cls.__name__} v{self.schema_version} > "
                    f"current v{cls.SCHEMA_VERSION}"
                ),
                user_action_required=True,
            )

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict. Includes schema_version and any
        preserved forward-compatible fields."""
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):  # type: ignore[arg-type]
            if f.name.startswith("_"):
                continue
            result[f.name] = getattr(self, f.name)
        # Round-trip: re-attach unknown fields captured at deserialization.
        extra: dict[str, Any] = getattr(self, "_extra_fields", {})
        result.update(extra)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Any:
        """Deserialize from dict with version and unknown-field checks.

        Raises ``CONTRACT_VERSION_UNSUPPORTED`` if *data* declares a version
        newer than ``SCHEMA_VERSION`` (future major with unknown required
        fields must NOT be silently accepted).
        """
        version = data.get("schema_version")
        if version is None:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.versioned",
                safe_message=f"{cls.__name__}: 'schema_version' is required",
            )
        if not isinstance(version, int):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.versioned",
                safe_message=(
                    f"{cls.__name__}: schema_version must be int, got {type(version).__name__}"
                ),
            )
        if version > cls.SCHEMA_VERSION:
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="contracts.versioned",
                safe_message=(
                    f"{cls.__name__} v{version} > supported v{cls.SCHEMA_VERSION}. "
                    f"Unknown required fields may be present."
                ),
                user_action_required=True,
            )
        if version < cls.MIN_SUPPORTED_VERSION:
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="contracts.versioned",
                safe_message=(
                    f"{cls.__name__} v{version} < min supported v{cls.MIN_SUPPORTED_VERSION}"
                ),
                user_action_required=True,
            )

        known_fields = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
        kwargs: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for key, value in data.items():
            if key in known_fields:
                kwargs[key] = value
            else:
                # Within supported version range → forward-compat optional field.
                extra[key] = value

        obj = cls(**kwargs)  # type: ignore[call-arg]
        if extra:
            object.__setattr__(obj, "_extra_fields", extra)
        return obj
