# SERAPHIM contracts — secret/sensitive data redaction (S04).
# Ensures secrets and stack traces never reach the UI (spec §14.2, TB-7).

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Key-based redaction: if a dict key matches, its value is replaced entirely.
# ---------------------------------------------------------------------------

_SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:"
    r"api_key|apikey|api_secret"
    r"|access_token|refresh_token|auth_token|token"
    r"|password|passwd|secret"
    r"|private_key|client_secret"
    r"|credential|authorization"
    r")(?:$|_)"
)

# ---------------------------------------------------------------------------
# Value-based redaction: patterns inside string values that look like secrets.
# ---------------------------------------------------------------------------

_SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    # OpenAI / Anthropic-style API keys
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{10,}\b"),
    # Generic "key=value" or "key: value" where key looks secret
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
    # Broader pattern: key=<value> where "key" ends in "secret", "key", "token", "password"
    re.compile(r"(?i)\b\w*(?:secret|key|token|password)\s*=\s*[^\s,\)]+"),
    # AWS-style keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # PEM private key blocks
    re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
    # Bearer tokens
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*\b"),
]

REDACTED = "[REDACTED]"


def sanitize_text(text: str) -> str:
    """Replace secret-like patterns in *text* with [REDACTED]."""
    result = text
    for pattern in _SECRET_VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def sanitize_value(value: Any) -> Any:
    """Recursively sanitize a value. Dict keys are checked for secret-like names."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return sanitize_dict(value)
    if isinstance(value, (list, tuple)):
        sanitized_list = [sanitize_value(item) for item in value]
        return type(value)(sanitized_list) if isinstance(value, tuple) else sanitized_list
    return value


def sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Deep-sanitize a dict: secret-like keys → value replaced, string values → pattern scrub."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and _SECRET_KEY_RE.search(key):
            result[key] = REDACTED
        else:
            result[key] = sanitize_value(value)
    return result


def strip_traceback(text: str) -> str:
    """Remove stack-trace lines from a string, keeping only the first line."""
    lines = text.splitlines()
    return lines[0] if lines else ""
