# SERAPHIM contracts — Result envelope (S04).
# Unified return type for operations that can fail with SeraphimError.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from seraphim.contracts.errors import SeraphimError

T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    """Success/failure envelope.  Exactly one of *value* or *error* is set."""

    ok: bool
    value: T | None = None
    error: SeraphimError | None = None

    # -- Constructors --------------------------------------------------------

    @staticmethod
    def success(value: T) -> Result[T]:
        return Result(ok=True, value=value)

    @staticmethod
    def failure(error: SeraphimError) -> Result[Any]:
        return Result(ok=False, error=error)

    # -- Guards --------------------------------------------------------------

    def unwrap(self) -> T:
        """Return the value or raise the error. Use at call-sites that require success."""
        if self.ok:
            if self.value is None:
                msg = "Result.ok is True but value is None"
                raise SeraphimError(
                    code="INTERNAL_ERROR",
                    component="contracts.result",
                    safe_message=msg,
                )
            return self.value
        if self.error is not None:
            raise self.error
        msg = "Result has ok=False but no error set"
        raise SeraphimError(
            code="INTERNAL_ERROR",
            component="contracts.result",
            safe_message=msg,
        )

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """User-safe serialization."""
        if self.ok:
            return {"ok": True, "value": _serialize_value(self.value)}
        return {"ok": False, "error": self.error.to_dict() if self.error else None}

    def to_diagnostic_dict(self) -> dict[str, Any]:
        """Diagnostic serialization."""
        if self.ok:
            return {"ok": True, "value": _serialize_value(self.value)}
        return {
            "ok": False,
            "error": self.error.to_diagnostic_dict() if self.error else None,
        }

    def __repr__(self) -> str:
        if self.ok:
            return f"Result.ok({self.value!r})"
        return f"Result.err({self.error!r})"


def _serialize_value(value: Any) -> Any:
    """Best-effort JSON-safe value serialization."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return str(value)
