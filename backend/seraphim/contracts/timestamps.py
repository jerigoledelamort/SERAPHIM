# SERAPHIM contracts — timestamp utilities (S04).
# All timestamps are ISO 8601 UTC strings (spec §4.16, CONTRACTS.md §8).

from __future__ import annotations

from datetime import UTC, datetime

_TS_RE = None  # Lazy-compiled on first use.


def now_utc() -> str:
    """Return current UTC time as an ISO 8601 string with 'Z' suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def validate_timestamp(ts: str) -> str:
    """Validate an ISO 8601 timestamp string. Returns *ts* if valid, raises ValueError."""
    if not isinstance(ts, str):
        msg = f"Timestamp must be a string, got {type(ts).__name__}"
        raise TypeError(msg)
    if not ts:
        msg = "Timestamp must not be empty"
        raise ValueError(msg)
    # Accept 'Z' suffix by replacing with +00:00 for fromisoformat compatibility.
    normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    try:
        datetime.fromisoformat(normalized)
    except (ValueError, TypeError) as exc:
        msg = f"Invalid ISO 8601 timestamp: {ts!r}"
        raise ValueError(msg) from exc
    return ts
