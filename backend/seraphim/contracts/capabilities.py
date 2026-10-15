# SERAPHIM contracts — capability model (S04).
# Namespace format per CONTRACTS.md §9, spec §7.4, ADR-011.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from seraphim.contracts.constants import RISK_LEVELS, SIDE_EFFECTS
from seraphim.contracts.errors import ErrorCode, SeraphimError

# Capability ID: <domain>.<subdomain>.<action> — lowercase, dot-separated, 2-3 parts.
_CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,2}$")


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SideEffect(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


def validate_capability_id(cap_id: str) -> str:
    """Validate capability ID format. Returns *cap_id* if valid, raises otherwise."""
    if not isinstance(cap_id, str):
        msg = f"Capability ID must be a string, got {type(cap_id).__name__}"
        raise TypeError(msg)
    if not _CAPABILITY_ID_RE.match(cap_id):
        msg = (
            f"Invalid capability ID: {cap_id!r}. "
            f"Expected '<domain>.<subdomain>.<action>' (lowercase, dot-separated, 2-3 parts)."
        )
        raise ValueError(msg)
    return cap_id


@dataclass
class Capability:
    """Capability contract per spec §7.4.

    Only the fields needed by the nearest stages (S05-S10) are included.
    """

    id: str
    name: str
    description: str = ""
    permissions: list[str] = field(default_factory=list)
    risk: str = "low"
    side_effects: str = "none"
    supports_cancellation: bool = True
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        validate_capability_id(self.id)
        if self.risk not in RISK_LEVELS:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.capabilities",
                safe_message=f"Invalid risk level: {self.risk!r}. Must be one of {RISK_LEVELS}",
            )
        if self.side_effects not in SIDE_EFFECTS:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.capabilities",
                safe_message=(
                    f"Invalid side_effects: {self.side_effects!r}. Must be one of {SIDE_EFFECTS}"
                ),
            )
        if not self.name:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.capabilities",
                safe_message="Capability name must not be empty",
            )
        if self.timeout_seconds <= 0:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="contracts.capabilities",
                safe_message=f"timeout_seconds must be positive, got {self.timeout_seconds}",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
            "risk": self.risk,
            "side_effects": self.side_effects,
            "supports_cancellation": self.supports_cancellation,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Capability:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            permissions=data.get("permissions", []),
            risk=data.get("risk", "low"),
            side_effects=data.get("side_effects", "none"),
            supports_cancellation=data.get("supports_cancellation", True),
            timeout_seconds=data.get("timeout_seconds", 30),
        )
