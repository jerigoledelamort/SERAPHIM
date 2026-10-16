# SERAPHIM contracts — secret/sensitive data redaction (S04).
# Ensures secrets and stack traces never reach the UI (spec §14.2, TB-7).

from __future__ import annotations

import re
from collections.abc import Iterable
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

# Keys whose value is a *reference* to a secret rather than the secret itself
# (S09).  Their value is kept (so an export stays restorable) only when it has
# the shape of a reference; anything else is a literal key pasted into the wrong
# field and is redacted.
_REFERENCE_KEYS = frozenset({"secret_ref", "credential_ref", "key_ref", "token_ref"})

#: Shape of a valid secret reference.  Mirrors ``sanctum.secrets.SECRET_REF_PATTERN``
#: (``contracts`` must not import ``sanctum``, so the pattern is duplicated and a
#: test keeps the two in sync).  A reference-shaped value contains no key material.
_SECRET_REF_VALUE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")

# ---------------------------------------------------------------------------
# Value-based redaction: patterns inside string values that look like secrets.
# ---------------------------------------------------------------------------

_SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    # OpenAI / Anthropic-style API keys ("sk-...", "sk-ant-...")
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{10,}\b"),
    # Google API keys
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    # Hugging Face tokens
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    # Slack tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-)
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
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
    # JWT (three base64url segments)
    re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\b"),
]

REDACTED = "[REDACTED]"

#: Minimum length of a value that may be redacted as a "known secret".
#: Shorter strings are ignored so that short refs/labels are not masked.
MIN_KNOWN_SECRET_LENGTH = 8

#: Process-wide registry of secret values that have been read into the process
#: (for example from the platform secret store, S09).  Every sanitizer consults
#: it, so a value that reached the process cannot be written back into a log, an
#: error, an event payload or an export even when its format matches no known
#: pattern.  This is deliberate global state: the alternative — threading a
#: redactor through every constructor — is easy to forget at one sink and then
#: the guarantee fails silently.  Values themselves are never exposed.
_KNOWN_SECRETS: set[str] = set()


def register_known_secret(known_values: str | Iterable[str] | None) -> None:
    """Register *known_values* as secret for the rest of the process.

    Called by the secret store whenever a value is read, so exact-value
    redaction covers sinks that were never told about the secret explicitly.
    """
    _KNOWN_SECRETS.update(
        value for value in _as_values(known_values) if len(value) >= MIN_KNOWN_SECRET_LENGTH
    )


def clear_known_secrets() -> None:
    """Forget every registered secret (used for test isolation)."""
    _KNOWN_SECRETS.clear()


def known_secret_count() -> int:
    """Number of registered secrets (values are never exposed)."""
    return len(_KNOWN_SECRETS)


def sanitize_text(text: str) -> str:
    """Replace secret-like patterns and registered secret values with [REDACTED]."""
    result = text
    for pattern in _SECRET_VALUE_PATTERNS:
        result = pattern.sub(REDACTED, result)
    if _KNOWN_SECRETS:
        result = redact_known_secrets(result, _KNOWN_SECRETS)
    return result


def redact_known_secrets(text: str, known_values: str | Iterable[str] | None) -> str:
    """Redact exact *known_values* occurrences in *text*, regardless of format.

    Pattern matching cannot catch every provider key format, so any value the
    runtime *knows* to be a secret (for example one read from the secret store)
    is removed by exact match. Values shorter than
    :data:`MIN_KNOWN_SECRET_LENGTH` are ignored to avoid masking short labels.

    Args:
        text: Text that may contain a secret value.
        known_values: An iterable of secret strings (or a single string).

    Returns:
        *text* with every known secret replaced by ``[REDACTED]``.

    Values registered process-wide via :func:`register_known_secret` are always
    removed as well.
    """
    # Longest first: prevents a shorter prefix from splitting a longer secret.
    for value in sorted(_as_values(known_values) | _KNOWN_SECRETS, key=len, reverse=True):
        if len(value) >= MIN_KNOWN_SECRET_LENGTH and value in text:
            text = text.replace(value, REDACTED)
    return text


def _as_values(known_values: str | Iterable[str] | None) -> set[str]:
    """Normalize the many accepted shapes of ``known_values`` into a set."""
    if known_values is None:
        return set()
    if isinstance(known_values, str):
        return {known_values}
    return {value for value in known_values if isinstance(value, str)}


class SecretRedactor:
    """Reusable redactor holding the set of currently known secret values.

    Used by logging/export paths so that a secret that has been read into the
    process can never be written back out, even if its format is unknown.
    """

    def __init__(self, known_values: str | Iterable[str] | None = None) -> None:
        self._values: set[str] = set()
        self.add(known_values)

    def add(self, known_values: str | Iterable[str] | None) -> None:
        """Register additional known secret values."""
        self._values.update(
            value for value in _as_values(known_values) if len(value) >= MIN_KNOWN_SECRET_LENGTH
        )

    @property
    def known_count(self) -> int:
        """Number of registered known secrets (values are never exposed)."""
        return len(self._values)

    def redact(self, text: str) -> str:
        """Pattern-scrub *text* and then remove every known secret value."""
        return redact_known_secrets(sanitize_text(text), self._values)

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Deep-redact a dict: key-based rules plus known-value removal."""
        return _redact_value(sanitize_dict(data), self._values)


def _redact_value(value: Any, known_values: set[str]) -> Any:
    if isinstance(value, str):
        return redact_known_secrets(value, known_values)
    if isinstance(value, dict):
        return {k: _redact_value(v, known_values) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_redact_value(item, known_values) for item in value]
        return tuple(items) if isinstance(value, tuple) else items
    return value


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
        if isinstance(key, str) and key.lower() in _REFERENCE_KEYS:
            # A reference is not a secret, but only a reference-shaped value is
            # kept: a literal key pasted into this field is redacted instead of
            # being written to an export, an error or an event.
            result[key] = _sanitize_reference_value(value)
        elif isinstance(key, str) and _SECRET_KEY_RE.search(key):
            result[key] = REDACTED
        else:
            result[key] = sanitize_value(value)
    return result


def _sanitize_reference_value(value: Any) -> Any:
    """Keep a reference-shaped string; redact anything else (S09).

    A reference is a logical name, so a non-string, or a value that cannot be a
    reference (spaces, uppercase, path separators, a recognized key format), is
    not a reference and is redacted.  A reference-shaped value is additionally
    pattern-scrubbed and checked against the registered secrets, which is the one
    case a shape check alone cannot catch: a pattern-free credential that happens
    to look like a name.
    """
    if isinstance(value, str) and _SECRET_REF_VALUE_RE.match(value):
        return sanitize_text(value)
    return REDACTED


def strip_traceback(text: str) -> str:
    """Remove stack-trace lines from a string, keeping only the first line."""
    lines = text.splitlines()
    return lines[0] if lines else ""
