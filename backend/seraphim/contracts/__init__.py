# SERAPHIM Layer 0 — Contracts (S04)
# Shared types, errors, events, IDs, capabilities, permissions.
# No dependencies on any other SERAPHIM module (CONTRACTS.md §3.1).

from seraphim.contracts.capabilities import Capability, RiskLevel, SideEffect
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event, Severity
from seraphim.contracts.ids import generate_id, id_prefix, validate_id
from seraphim.contracts.permissions import Permission
from seraphim.contracts.result import Result
from seraphim.contracts.sanitization import sanitize_dict, sanitize_text
from seraphim.contracts.timestamps import now_utc, validate_timestamp
from seraphim.contracts.versioned import VersionedEntity

__all__ = [
    "Capability",
    "ErrorCode",
    "Event",
    "Permission",
    "Result",
    "RiskLevel",
    "SeraphimError",
    "Severity",
    "SideEffect",
    "VersionedEntity",
    "generate_id",
    "id_prefix",
    "now_utc",
    "sanitize_dict",
    "sanitize_text",
    "validate_id",
    "validate_timestamp",
]
