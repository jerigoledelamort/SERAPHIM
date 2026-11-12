from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint(tool_id: str, version: str, arguments: dict) -> str:
    raw = json.dumps([tool_id, version, arguments], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def state_digest(paths: tuple[str, ...]) -> str:
    observed = []
    for name in paths:
        path = Path(name)
        try:
            if path.is_symlink():
                value = "unavailable"
            elif not path.exists():
                value = "absent"
            elif path.is_file() and path.stat().st_size <= 1048576:
                value = hashlib.sha256(path.read_bytes()).hexdigest()
            elif path.is_dir():
                value = "directory"
            else:
                value = "unavailable"
        except OSError:
            value = "unavailable"
        observed.append((name, value))
    return hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()


def inspect(history: list[str], current: str, *, repeated: int = 3) -> str:
    recent = history[-16:]
    if recent.count(current) >= repeated - 1:
        return "canonical action repeated without independent progress"
    sequence = [*recent, current]
    if len(sequence) >= 6 and sequence[-6:-4] == sequence[-4:-2] == sequence[-2:]:
        return "alternating action cycle without independent progress"
    return ""
