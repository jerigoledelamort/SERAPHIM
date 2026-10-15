# SERAPHIM contracts — permission model (S04).
# Dot-separated permission strings (spec §4.3, §4.8).

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Permission format: lowercase dot-separated segments, 1-4 parts.
# Examples: "filesystem.read", "shell.execute", "network.http.get"
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,3}$")


def validate_permission(perm: str) -> str:
    """Validate a permission string. Returns *perm* if valid, raises otherwise."""
    if not isinstance(perm, str):
        msg = f"Permission must be a string, got {type(perm).__name__}"
        raise TypeError(msg)
    if not _PERMISSION_RE.match(perm):
        msg = (
            f"Invalid permission: {perm!r}. "
            f"Expected lowercase dot-separated (1-4 parts), e.g. 'filesystem.read'."
        )
        raise ValueError(msg)
    return perm


@dataclass(frozen=True)
class Permission:
    """A single permission with optional scope constraint.

    ``scope`` restricts the permission to a specific area
    (e.g. project path, application ID).
    """

    name: str
    scope: str = ""

    def __post_init__(self) -> None:
        validate_permission(self.name)

    def __str__(self) -> str:
        return f"{self.name}({self.scope})" if self.scope else self.name

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name}
        if self.scope:
            result["scope"] = self.scope
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Permission:
        return cls(
            name=data["name"],
            scope=data.get("scope", ""),
        )
