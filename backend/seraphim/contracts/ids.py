# SERAPHIM contracts — prefixed ID generation and validation (S04).
# Format: <prefix>_<uuid4> per spec §4.1, §14.1.

from __future__ import annotations

import re
import uuid

from seraphim.contracts.constants import ID_PREFIXES

# Pattern: lowercase alpha/underscore prefix, then underscore, then UUID4.
_ID_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def generate_id(prefix: str) -> str:
    """Generate a new prefixed UUID4 ID.

    Raises ValueError if *prefix* is not in the allowed set.
    """
    if prefix not in ID_PREFIXES:
        msg = f"Unknown ID prefix: {prefix!r}. Must be one of {sorted(ID_PREFIXES)}"
        raise ValueError(msg)
    return f"{prefix}_{uuid.uuid4()}"


def validate_id(id_str: str) -> str:
    """Validate a prefixed ID string. Returns *id_str* if valid, raises ValueError otherwise."""
    if not isinstance(id_str, str):
        msg = f"ID must be a string, got {type(id_str).__name__}"
        raise TypeError(msg)
    match = _ID_RE.match(id_str)
    if not match:
        msg = f"Invalid ID format: {id_str!r}. Expected '<prefix>_<uuid4>'."
        raise ValueError(msg)
    prefix = match.group(1)
    if prefix not in ID_PREFIXES:
        msg = f"Unknown ID prefix: {prefix!r}. Must be one of {sorted(ID_PREFIXES)}"
        raise ValueError(msg)
    return id_str


def id_prefix(id_str: str) -> str:
    """Extract the prefix from a prefixed ID.

    Uses the UUID pattern to split, so prefixes containing underscores
    (e.g. 'correlation') are handled correctly.
    """
    match = _ID_RE.match(id_str)
    if not match:
        msg = f"Cannot extract prefix from invalid ID: {id_str!r}"
        raise ValueError(msg)
    return match.group(1)
