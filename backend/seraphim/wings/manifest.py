# WINGS tool manifest (S19): the single description of a tool. Pure data; no
# implementation reference. Validation here is structural only: whether a tool
# may run is decided by AEGIS (S20), not by its manifest.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.capabilities import validate_capability_id
from seraphim.contracts.constants import RISK_LEVELS, SIDE_EFFECTS
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.permissions import validate_permission

COMPONENT = "wings.manifest"

MANIFEST_SCHEMA_VERSION = 1

TOOL_SOURCES = ("core", "mcp", "bridges", "skill")
IDEMPOTENCY = ("idempotent", "non_idempotent", "unknown")


def _invalid(message: str) -> SeraphimError:
    return SeraphimError(code=ErrorCode.TOOL_SCHEMA_INVALID, component=COMPONENT, safe_message=message)


def validate_json_schema(schema: Any, where: str) -> dict[str, Any]:
    """Accept only a JSON-Schema object with a string ``type`` of ``object`` or a known scalar."""
    if not isinstance(schema, dict):
        raise _invalid(f"{where} must be a JSON Schema object")
    declared = schema.get("type")
    if declared is None:
        raise _invalid(f"{where} must declare a type")
    allowed = {"object", "array", "string", "number", "integer", "boolean", "null"}
    if declared not in allowed:
        raise _invalid(f"{where} has unsupported type {declared!r}")
    if declared == "object" and "properties" in schema and not isinstance(schema["properties"], dict):
        raise _invalid(f"{where} properties must be an object")
    return schema


@dataclass(frozen=True)
class ToolManifest:
    id: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    capabilities: tuple[str, ...]
    risk: str
    side_effects: str
    permissions: tuple[str, ...]
    timeout_seconds: int
    supports_cancellation: bool
    idempotency: str
    source: str
    version: str
    tags: tuple[str, ...] = field(default=())
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise _invalid(f"Tool {self.id} has unsupported schema_version {self.schema_version!r}")
        if not self.id.startswith("tool.") or len(self.id) <= len("tool."):
            raise _invalid(f"Tool id must be namespaced as tool.<name>, got {self.id!r}")
        if not self.description.strip():
            raise _invalid(f"Tool {self.id} needs a description")
        validate_json_schema(self.input_schema, f"Tool {self.id} input_schema")
        validate_json_schema(self.output_schema, f"Tool {self.id} output_schema")
        if not self.capabilities:
            raise _invalid(f"Tool {self.id} must declare at least one capability")
        for cap in self.capabilities:
            validate_capability_id(cap)
        if len(set(self.capabilities)) != len(self.capabilities):
            raise _invalid(f"Tool {self.id} lists a capability twice")
        if self.risk not in RISK_LEVELS:
            raise _invalid(f"Tool {self.id} has unknown risk {self.risk!r}")
        if self.side_effects not in SIDE_EFFECTS:
            raise _invalid(f"Tool {self.id} has unknown side_effects {self.side_effects!r}")
        for perm in self.permissions:
            validate_permission(perm)
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool):
            raise _invalid(f"Tool {self.id} timeout_seconds must be an integer")
        if not 1 <= self.timeout_seconds <= 600:
            raise _invalid(f"Tool {self.id} timeout_seconds must be 1..600")
        if self.idempotency not in IDEMPOTENCY:
            raise _invalid(f"Tool {self.id} has unknown idempotency {self.idempotency!r}")
        if self.source not in TOOL_SOURCES:
            raise _invalid(f"Tool {self.id} has unknown source {self.source!r}")
        if not self.version or not all(part.isdigit() for part in self.version.split(".")):
            raise _invalid(f"Tool {self.id} version must be dotted integers, e.g. 1.0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "capabilities": list(self.capabilities),
            "risk": self.risk,
            "side_effects": self.side_effects,
            "permissions": list(self.permissions),
            "timeout_seconds": self.timeout_seconds,
            "supports_cancellation": self.supports_cancellation,
            "idempotency": self.idempotency,
            "source": self.source,
            "version": self.version,
            "tags": list(self.tags),
            "schema_version": self.schema_version,
        }

