# WINGS filesystem path guard (S21): every path is resolved inside a root one component
# at a time. Links and junctions are refused, not followed. Secret-looking components
# anywhere in the path are refused even inside an allowed root.

from __future__ import annotations

import os
import stat
from pathlib import Path, PureWindowsPath

from seraphim.contracts.errors import ErrorCode, SeraphimError

COMPONENT = "wings.fs"

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_SECRET_NAMES = frozenset(
    {
        ".git", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".netrc", ".npmrc",
        ".pypirc", ".seraphim", "id_rsa", "id_ed25519", "credentials", "keys", "secrets",
    }
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx", ".ppk")
_SECRET_MARKERS = ("secret", "credential", "password", "token", ".env")


def is_secret_component(name: str) -> bool:
    lowered = name.lower()
    if lowered in _SECRET_NAMES or lowered.startswith(".env"):
        return True
    if lowered.endswith(_SECRET_SUFFIXES):
        return True
    return any(marker in lowered for marker in _SECRET_MARKERS)


def is_link_or_junction(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def denied(message: str) -> SeraphimError:
    return SeraphimError(code=ErrorCode.FS_PATH_DENIED, component=COMPONENT, safe_message=message)


def _check_name(name: str) -> None:
    if name in ("", ".."):
        raise denied("Path traversal is not allowed.")
    if ":" in name or "\x00" in name:
        raise denied("Path contains a forbidden character.")
    if name != name.rstrip(" ."):
        raise denied("Path component ends with a dot or space.")
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        raise denied("Path uses a reserved device name.")
    if is_secret_component(name):
        raise denied("Path points into a protected location.")


def _is_within(root: str, candidate: str) -> bool:
    root_key = os.path.normcase(root)
    candidate_key = os.path.normcase(candidate)
    return candidate_key == root_key or candidate_key.startswith(root_key + os.sep)


class FsRoot:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        raw = os.fspath(path)
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise denied("Root path is invalid.")
        resolved = os.path.realpath(raw)
        if not os.path.isdir(resolved):
            raise SeraphimError(
                code=ErrorCode.FS_NOT_FOUND, component=COMPONENT, safe_message="Root directory does not exist."
            )
        self._root = resolved

    @property
    def path(self) -> Path:
        return Path(self._root)

    def resolve(self, relative: str, *, must_exist: bool = True) -> Path:
        if not isinstance(relative, str) or not relative:
            raise denied("Path must be a non-empty string.")
        if "\x00" in relative or ":" in relative:
            raise denied("Path contains a forbidden character.")
        if relative.startswith(("/", "\\")) or PureWindowsPath(relative).is_absolute():
            raise denied("Absolute paths are not allowed.")
        parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
        for name in parts:
            _check_name(name)

        current = Path(self._root)
        for index, name in enumerate(parts):
            current = current / name
            try:
                st = os.lstat(current)
            except FileNotFoundError:
                if must_exist:
                    raise SeraphimError(
                        code=ErrorCode.FS_NOT_FOUND, component=COMPONENT, safe_message="Path does not exist."
                    ) from None
                current = current.joinpath(*parts[index + 1 :])
                break
            if is_link_or_junction(st):
                raise denied("Links and junctions are not followed.")

        real = os.path.realpath(current)
        if not _is_within(self._root, real):
            raise denied("Path resolves outside the allowed root.")
        return current
