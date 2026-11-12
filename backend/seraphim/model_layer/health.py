# SERAPHIM MODEL LAYER — provider health contract (S12).
#
# Health is an explicit, provider-reported status, never inferred from the model
# name or from a single successful call.  PULSE (S06) aggregates these values.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.sanitization import sanitize_dict, sanitize_text
from seraphim.contracts.timestamps import now_utc


class HealthStatus(StrEnum):
    """Mirrors the PULSE status vocabulary (spec §4.17, CONTRACTS.md §2.19)."""

    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    UNKNOWN = "UNKNOWN"


@dataclass
class ProviderHealth:
    """Result of a provider health check.

    ``detail`` is a *safe* human-readable note; it must not contain credentials
    (the provider is responsible, and ``SeraphimError`` sanitizes errors anyway).
    """

    status: str
    provider_id: str = ""
    model: str = ""
    latency_ms: float | None = None
    checked_at: str = ""
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in set(HealthStatus):
            self.status = HealthStatus.UNKNOWN
        if not self.checked_at:
            self.checked_at = now_utc()
        # PULSE (S06) aggregates these values, so they must be as safe as an
        # error envelope: a health detail is not a place for a credential.
        self.detail = sanitize_text(self.detail)
        if self.metadata:
            self.metadata = sanitize_dict(self.metadata)

    @property
    def is_available(self) -> bool:
        return self.status in (HealthStatus.ONLINE, HealthStatus.DEGRADED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider_id": self.provider_id,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            # Re-sanitized here: PULSE aggregates this value and the dataclass is
            # mutable, so a late write must not reach a dump (S12 MINOR B).
            "detail": sanitize_text(self.detail),
            "metadata": sanitize_dict(self.metadata) if self.metadata else {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderHealth:
        return cls(
            status=data.get("status", HealthStatus.UNKNOWN),
            provider_id=data.get("provider_id", ""),
            model=data.get("model", ""),
            latency_ms=data.get("latency_ms"),
            checked_at=data.get("checked_at", ""),
            detail=data.get("detail", ""),
            metadata=data.get("metadata", {}),
        )


__all__ = ["HealthStatus", "ProviderHealth"]
