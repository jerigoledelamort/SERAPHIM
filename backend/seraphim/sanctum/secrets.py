# SERAPHIM SANCTUM — provider secret storage (S09).
#
# Spec §4.5: "API keys хранятся в защищённом хранилище/зашифрованном секрете,
# не в открытых логах".  CONTRACTS.md §4.4: secrets are never stored in YAML
# config, logs, exports (by default) or test fixtures.  TB-7: secrets → outward.
#
# Design:
#   - Configuration stores only a logical reference (``secret_ref``), never a
#     value.  A literal key pasted into a config file is rejected by the loader
#     when it matches a known key format, and any other value under a reference
#     key is redacted by the sanitizer (``contracts.sanitization``).
#   - ``SecretStore`` is the single interface.  The default backend is the
#     Windows Data Protection API (DPAPI) accessed through ``ctypes`` (no new
#     dependency): the ciphertext lives in ``<root>/data/secrets/<ref>.bin``
#     inside the SERAPHIM root (§12.1 single root) and is decryptable only by
#     the same OS user on the same machine.
#   - If no secure backend is available the store *fails closed*
#     (``SECRET_STORE_UNAVAILABLE``) instead of silently writing plaintext.
#     A plaintext fallback is never selected automatically.
#   - Secret values are never logged, never serialized, and never returned by
#     listing/describe APIs.  Only masked displays (``****abcd``) are exposed.

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wintypes
import os
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import (
    REDACTED,
    redact_known_secrets,
    register_known_secret,
    sanitize_text,
)

COMPONENT = "sanctum.secrets"

# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

#: A secret reference is a logical name used both as a config value and as the
#: on-disk file stem.  It must start and end with an alphanumeric character so
#: that ``.``, ``..`` and leading-dot names can never be produced, and it may
#: not contain a path separator.
SECRET_REF_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")

SECRET_REF_MAX_LENGTH = 64

#: Windows reserved device names: ``con.bin`` cannot be created as a file.
_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

#: Number of trailing characters shown in a masked display.
MASK_VISIBLE_CHARS = 4

MASK_PREFIX = "****"


def validate_secret_ref(ref: str) -> str:
    """Validate a secret reference and return it unchanged.

    Args:
        ref: Candidate reference (config value / CLI argument).

    Returns:
        The validated reference.

    Raises:
        SeraphimError: ``SECRET_REF_INVALID`` if the reference is malformed.
    """
    if not isinstance(ref, str):
        raise _fail(
            ErrorCode.SECRET_REF_INVALID,
            f"Secret reference must be a string, got {type(ref).__name__}.",
            details={"ref_type": type(ref).__name__},
        )
    if not ref:
        raise _fail(ErrorCode.SECRET_REF_INVALID, "Secret reference must not be empty.")
    if len(ref) > SECRET_REF_MAX_LENGTH:
        raise _fail(
            ErrorCode.SECRET_REF_INVALID,
            f"Secret reference is longer than {SECRET_REF_MAX_LENGTH} characters.",
            details={"length": len(ref)},
        )
    if not SECRET_REF_PATTERN.match(ref):
        raise _fail(
            ErrorCode.SECRET_REF_INVALID,
            "Secret reference must match "
            f"{SECRET_REF_PATTERN.pattern} (lowercase letters, digits, '.', '_', '-').",
            details={"ref_length": len(ref)},
        )
    if ref.split(".")[0] in _RESERVED_DEVICE_NAMES:
        raise _fail(
            ErrorCode.SECRET_REF_INVALID,
            "Secret reference must not use a reserved device name.",
            details={"ref": ref},
        )
    return ref


def mask_secret(value: str, *, visible: int = MASK_VISIBLE_CHARS) -> str:
    """Return a display-safe mask for *value*; the value itself is never shown.

    Only the trailing ``visible`` characters are revealed, which is enough for a
    human to tell two keys apart without exposing the secret.
    """
    if not isinstance(value, str):
        return MASK_PREFIX
    if visible <= 0 or len(value) <= visible:
        return MASK_PREFIX
    return f"{MASK_PREFIX}{value[-visible:]}"


def looks_like_secret(value: str) -> bool:
    """True if *value* looks like a literal secret rather than a reference.

    Used by the config loader to reject a raw API key pasted into a config file
    instead of a ``secret_ref``.
    """
    if not isinstance(value, str) or not value:
        return False
    return sanitize_text(value) != value


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def _fail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    user_action_required: bool = False,
    details: dict[str, Any] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def secret_not_found(ref: str) -> SeraphimError:
    """Structured error for a reference with no stored value."""
    return _fail(
        ErrorCode.SECRET_NOT_FOUND,
        f"No secret is stored under reference '{ref}'. "
        f"Set it with: seraphim secrets set {ref}",
        user_action_required=True,
        details={"ref": ref},
    )


def secret_store_unavailable(reason: str) -> SeraphimError:
    """Structured error for a platform without a usable secure backend."""
    return _fail(
        ErrorCode.SECRET_STORE_UNAVAILABLE,
        "No platform secure storage backend is available, so secrets cannot be "
        f"stored safely ({reason}). Plaintext storage is not used as a fallback.",
        user_action_required=True,
        details={"reason": reason},
    )


def provider_auth_error(
    provider: str,
    secret_ref: str = "",
    *,
    status: int | None = None,
    key_value: str | None = None,
    detail: str = "",
    component: str = "model_layer.provider",
) -> SeraphimError:
    """Build a ``PROVIDER_AUTH_FAILED`` error that never carries the key value.

    Acceptance criterion (S09): an auth error must not reveal the key.  The
    provider adapter holds the value, so it passes it here as ``key_value`` and
    every occurrence is removed from the message before the error is created —
    including values whose format no pattern would recognize.  Only the
    reference name and the HTTP status are reported.

    Args:
        provider: Provider identifier (e.g. ``"openai"``).
        secret_ref: Reference the failed credential was read from.
        status: HTTP status, when known.
        key_value: The key value that must never appear in the error.
        detail: Extra context; scrubbed as well.
        component: Owning component for the error envelope.
    """
    message = f"Authentication with provider '{provider}' failed"
    if status is not None:
        message += f" (HTTP {status})"
    if detail:
        message += f": {detail}"
    if secret_ref:
        message += f" [secret_ref={secret_ref}]"
    return SeraphimError(
        code=ErrorCode.PROVIDER_AUTH_FAILED,
        component=component,
        safe_message=redact_known_secrets(message, key_value),
        user_action_required=True,
        details={
            "provider": provider,
            "secret_ref": secret_ref,
            "status": status,
            # Never the value; the reference is enough to fix the problem.
            # (Key name avoids the secret-key patterns so the flag survives.)
            "value_supplied": bool(key_value),
        },
    )


# ---------------------------------------------------------------------------
# Backend description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretStoreInfo:
    """Where secrets physically live, for display in settings/diagnostics.

    Contains no secret material: only the backend name and the logical
    directory.  ``persistent`` tells the user whether values survive a restart.
    """

    backend: str
    location: str
    persistent: bool
    encrypted_at_rest: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "location": self.location,
            "persistent": self.persistent,
            "encrypted_at_rest": self.encrypted_at_rest,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SecretRefStatus:
    """Metadata about one stored reference (never the value)."""

    ref: str
    present: bool
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "present": self.present, "backend": self.backend}


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class SecretStore(ABC):
    """Single interface for provider secret storage (SANCTUM-owned).

    Implementations must never log, serialize or return a stored value except
    through :meth:`get`, which is the only value-returning method.
    """

    #: Short backend identifier ("dpapi", "memory", "unavailable").
    backend: str = "unknown"

    @property
    @abstractmethod
    def info(self) -> SecretStoreInfo:
        """Backend description for user-facing settings (no secret material)."""

    @abstractmethod
    def set(self, ref: str, value: str) -> None:
        """Store *value* under *ref* (creating or overwriting)."""

    @abstractmethod
    def get(self, ref: str) -> str:
        """Return the stored value for *ref*.

        Raises:
            SeraphimError: ``SECRET_NOT_FOUND`` / ``SECRET_ACCESS_DENIED``.
        """

    @abstractmethod
    def has(self, ref: str) -> bool:
        """True if a value is stored under *ref* (without decrypting it)."""

    @abstractmethod
    def delete(self, ref: str) -> bool:
        """Delete *ref*; returns True if something was removed."""

    @abstractmethod
    def list_refs(self) -> list[str]:
        """Sorted list of stored reference names (never values)."""

    # -- Non-abstract conveniences -------------------------------------------

    def rotate(self, ref: str, new_value: str) -> None:
        """Replace the value of an existing reference.

        Rotation is refused when the reference does not exist, so a typo cannot
        silently create a second credential.
        """
        validate_secret_ref(ref)
        if not self.has(ref):
            raise secret_not_found(ref)
        self.set(ref, new_value)

    def masked(self, ref: str) -> str:
        """Masked display of the stored value (``****abcd``)."""
        return mask_secret(self.get(ref))

    def statuses(self) -> list[SecretRefStatus]:
        """Reference list with presence flags, for display."""
        return [
            SecretRefStatus(ref=ref, present=True, backend=self.backend)
            for ref in self.list_refs()
        ]


# ---------------------------------------------------------------------------
# In-memory backend (tests / ephemeral runs; never selected automatically)
# ---------------------------------------------------------------------------


class InMemorySecretStore(SecretStore):
    """Non-persistent store for tests and ephemeral runs.

    Explicitly opt-in: it is never chosen by :func:`create_secret_store`, so a
    test convenience cannot become the production default.
    """

    backend = "memory"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    @property
    def info(self) -> SecretStoreInfo:
        return SecretStoreInfo(
            backend=self.backend,
            location="(process memory)",
            persistent=False,
            encrypted_at_rest=False,
            detail="Values are lost when the process exits.",
        )

    def set(self, ref: str, value: str) -> None:
        validate_secret_ref(ref)
        _require_value(value)
        self._values[ref] = value

    def get(self, ref: str) -> str:
        validate_secret_ref(ref)
        if ref not in self._values:
            raise secret_not_found(ref)
        value = self._values[ref]
        register_known_secret(value)
        return value

    def has(self, ref: str) -> bool:
        validate_secret_ref(ref)
        return ref in self._values

    def delete(self, ref: str) -> bool:
        validate_secret_ref(ref)
        return self._values.pop(ref, None) is not None

    def list_refs(self) -> list[str]:
        return sorted(self._values)


# ---------------------------------------------------------------------------
# Fail-closed backend
# ---------------------------------------------------------------------------


class UnavailableSecretStore(SecretStore):
    """Fail-closed backend used when no secure mechanism exists.

    Every mutating or reading operation raises ``SECRET_STORE_UNAVAILABLE``.
    This exists so that an unsupported platform degrades to a clear error rather
    than to plaintext storage.
    """

    backend = "unavailable"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    @property
    def info(self) -> SecretStoreInfo:
        return SecretStoreInfo(
            backend=self.backend,
            location="(none)",
            persistent=False,
            encrypted_at_rest=False,
            detail=self._reason,
        )

    def _raise(self) -> None:
        raise secret_store_unavailable(self._reason)

    def set(self, ref: str, value: str) -> None:
        self._raise()

    def get(self, ref: str) -> str:
        self._raise()

    def has(self, ref: str) -> bool:
        return False

    def delete(self, ref: str) -> bool:
        self._raise()

    def list_refs(self) -> list[str]:
        return []


# ---------------------------------------------------------------------------
# Windows DPAPI backend
# ---------------------------------------------------------------------------

#: File magic so a foreign/corrupted file is rejected instead of misparsed.
_DPAPI_FILE_MAGIC = b"SRP1"

#: Optional entropy: a fixed, *non-secret* domain separator.  It is not a key;
#: it only binds ciphertext to this application's DPAPI usage.  A process
#: running as the same user could still decrypt the file (documented limit).
_DPAPI_ENTROPY = b"seraphim.sanctum.secrets.v1"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_from(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _blob_to(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _load_crypt32() -> Any | None:
    if sys.platform != "win32":
        return None
    try:
        return ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined]
    except OSError:
        return None


def _dpapi_protect(crypt32: Any, kernel32: Any, data: bytes) -> bytes:
    data_in = _blob_from(data)
    entropy = _blob_from(_DPAPI_ENTROPY)
    data_out = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return _blob_to(data_out)
    finally:
        kernel32.LocalFree(data_out.pbData)


def _dpapi_unprotect(crypt32: Any, kernel32: Any, data: bytes) -> bytes:
    data_in = _blob_from(data)
    entropy = _blob_from(_DPAPI_ENTROPY)
    data_out = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return _blob_to(data_out)
    finally:
        kernel32.LocalFree(data_out.pbData)


def dpapi_available() -> tuple[bool, str]:
    """Probe DPAPI with a round-trip. Returns ``(available, reason)``.

    The capability is verified rather than assumed: a platform that claims to be
    Windows but cannot complete a protect/unprotect round-trip is treated as
    unavailable.
    """
    crypt32 = _load_crypt32()
    if crypt32 is None:
        return False, "not running on Windows (DPAPI unavailable)"
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    except OSError as exc:  # pragma: no cover - defensive
        return False, f"kernel32 unavailable: {exc}"

    probe = b"seraphim-dpapi-probe"
    try:
        if _dpapi_unprotect(crypt32, kernel32, _dpapi_protect(crypt32, kernel32, probe)) != probe:
            return False, "DPAPI round-trip returned unexpected data"
    except OSError as exc:
        return False, f"DPAPI round-trip failed: {exc.strerror or exc}"
    return True, ""


class DPAPISecretStore(SecretStore):
    """Windows DPAPI backend: ciphertext files inside the SERAPHIM root.

    Physical location: ``<root>/data/secrets/<ref>.bin``.  Each file contains a
    ``SRP1`` magic followed by a DPAPI blob.  The key that encrypts the blob is
    the OS user's credential master key, managed by Windows — SERAPHIM never
    holds a passphrase, which is why this variant does not need key management
    (the objection recorded in ADR-006 for variant 2).

    Limits (documented, not hidden):
      - The ciphertext is bound to the OS user and machine: copying the file to
        another account or machine does not yield the secret.
      - It protects data *at rest*.  Another process running as the same user
        can decrypt it; DPAPI is not a defence against a compromised session.
    """

    backend = "dpapi"

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        secrets_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self._root = Path(os.path.abspath(str(root)))
        self._dir = (
            Path(secrets_dir) if secrets_dir is not None else self._root / "data" / "secrets"
        )
        self._crypt32 = _load_crypt32()
        if self._crypt32 is None:  # pragma: no cover - guarded by factory
            raise secret_store_unavailable("not running on Windows (DPAPI unavailable)")
        try:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        except OSError as exc:  # pragma: no cover - defensive
            raise secret_store_unavailable(f"kernel32 unavailable: {exc}") from exc

    # -- Layout --------------------------------------------------------------

    @property
    def info(self) -> SecretStoreInfo:
        return SecretStoreInfo(
            backend=self.backend,
            location=str(self._dir),
            persistent=True,
            encrypted_at_rest=True,
            detail=(
                "Windows DPAPI ciphertext, decryptable only by the current OS user "
                "on this machine."
            ),
        )

    def path_for(self, ref: str) -> Path:
        """Absolute path of the ciphertext file for *ref*."""
        return self._dir / f"{validate_secret_ref(ref)}.bin"

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        # Best effort: Windows enforces access through ACLs, not POSIX modes.
        with contextlib.suppress(OSError):
            os.chmod(self._dir, 0o700)

    # -- Operations ----------------------------------------------------------

    def set(self, ref: str, value: str) -> None:
        validate_secret_ref(ref)
        _require_value(value)
        self._ensure_dir()
        payload = _DPAPI_FILE_MAGIC + _dpapi_protect(
            self._crypt32, self._kernel32, value.encode("utf-8")
        )
        target = self.path_for(ref)
        # Atomic replace: a crash mid-write cannot leave a truncated secret file.
        tmp = target.with_suffix(".bin.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, target)

    def get(self, ref: str) -> str:
        validate_secret_ref(ref)
        target = self.path_for(ref)
        if not target.is_file():
            raise secret_not_found(ref)
        raw = target.read_bytes()
        if not raw.startswith(_DPAPI_FILE_MAGIC):
            raise _fail(
                ErrorCode.SECRET_ACCESS_DENIED,
                f"Stored secret '{ref}' is not a SERAPHIM secret file.",
                details={"ref": ref},
            )
        try:
            plaintext = _dpapi_unprotect(
                self._crypt32, self._kernel32, raw[len(_DPAPI_FILE_MAGIC) :]
            )
        except OSError as exc:
            raise _fail(
                ErrorCode.SECRET_ACCESS_DENIED,
                f"Stored secret '{ref}' could not be decrypted for this user/machine.",
                user_action_required=True,
                details={"ref": ref, "error": exc.strerror or "decryption failed"},
            ) from exc
        value = plaintext.decode("utf-8")
        # A value that has been read into the process is registered as a known
        # secret, so no sink (log, error, event, export) can write it back out —
        # even if its format matches no known key pattern.
        register_known_secret(value)
        return value

    def has(self, ref: str) -> bool:
        validate_secret_ref(ref)
        return self.path_for(ref).is_file()

    def delete(self, ref: str) -> bool:
        validate_secret_ref(ref)
        target = self.path_for(ref)
        if not target.is_file():
            return False
        target.unlink()
        return True

    def list_refs(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        refs = [
            entry.stem
            for entry in self._dir.glob("*.bin")
            if entry.is_file() and SECRET_REF_PATTERN.match(entry.stem)
        ]
        return sorted(refs)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_secret_store(
    root: str | os.PathLike[str],
    *,
    backend: str | None = None,
    secrets_dir: str | os.PathLike[str] | None = None,
    platform: str | None = None,
) -> SecretStore:
    """Select the secret store backend for *root*.

    Selection is deterministic and fail-closed:

    - ``backend="memory"`` → :class:`InMemorySecretStore` (tests/ephemeral only).
    - ``backend="dpapi"`` → :class:`DPAPISecretStore`; when the platform cannot
      complete a DPAPI round-trip this degrades to
      :class:`UnavailableSecretStore`, which raises ``SECRET_STORE_UNAVAILABLE``
      on first use rather than at construction time.
    - ``backend=None`` → platform default: DPAPI on Windows, otherwise an
      :class:`UnavailableSecretStore` that raises ``SECRET_STORE_UNAVAILABLE``.

    There is deliberately no plaintext-file backend: a fallback must be an
    explicit, reviewed decision (ADR-006), not an implicit default.
    """
    platform_name = platform if platform is not None else sys.platform

    if backend == "memory":
        return InMemorySecretStore()

    if backend == "dpapi" or (backend is None and platform_name == "win32"):
        available, reason = dpapi_available()
        if not available:
            return UnavailableSecretStore(reason)
        return DPAPISecretStore(root, secrets_dir=secrets_dir)

    if backend is not None and backend != "dpapi":
        raise _fail(
            ErrorCode.VALIDATION_FAILED,
            f"Unknown secret store backend '{backend}'.",
            details={"backend": backend},
        )

    return UnavailableSecretStore(
        f"no secure backend configured for platform '{platform_name}'"
    )


def redacted(value: str) -> str:
    """Always-redacted placeholder (never returns the input)."""
    return REDACTED


def _require_value(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _fail(ErrorCode.VALIDATION_FAILED, "Secret value must be a non-empty string.")
