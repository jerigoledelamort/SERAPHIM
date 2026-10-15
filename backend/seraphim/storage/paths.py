# SERAPHIM storage — runtime database path resolution (S05).
#
# Spec §12.1/§12.2: everything, including the SQLite database, lives inside the
# SERAPHIM root unless the user explicitly chose another location.  CONTRACTS.md
# §4.3 fixes the default location as ``data/seraphim.sqlite``.
#
# Resolution priority (highest first):
#   1. explicit ``db_path`` argument (tests, CLI flag)
#   2. ``SERAPHIM_DB_PATH`` environment variable (tests, portable installs)
#   3. ``<root>/data/seraphim.sqlite`` default
#
# Relative override values are always resolved *against the root*, never against
# the current working directory, so a relative value cannot silently escape.
# Absolute values outside the root are rejected unless ``allow_external=True``
# (documented exception path for users who moved the database).

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from seraphim.contracts.errors import ErrorCode, SeraphimError

COMPONENT = "storage.paths"

#: Default database location relative to the SERAPHIM root (CONTRACTS.md §4.3).
DEFAULT_DB_RELATIVE_PATH: tuple[str, ...] = ("data", "seraphim.sqlite")

#: Environment variable that overrides the database path (tests / portable mode).
DB_PATH_ENV_VAR = "SERAPHIM_DB_PATH"

#: SQLite special names that must never be treated as filesystem paths.
_RESERVED_TARGETS = (":memory:", ":temp:", ":private:")


class PathSource:
    """Where the resolved database path came from."""

    DEFAULT = "default"
    ENV = "env"
    ARGUMENT = "argument"


@dataclass(frozen=True)
class ResolvedDBPath:
    """Result of database path resolution."""

    path: Path
    root: Path
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "root": str(self.root),
            "source": self.source,
        }


def _fail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    user_action_required: bool = False,
    details: dict[str, object] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def _normalized_key(path: Path) -> str:
    """Case/separator-insensitive key used for containment comparison.

    Windows filesystems are case-insensitive, so plain ``PurePath`` comparison
    would let ``D:\\ROOT`` and ``d:\\root`` disagree.
    """
    return os.path.normcase(os.path.abspath(str(path)))


def _is_within(root: Path, candidate: Path) -> bool:
    root_key = _normalized_key(root)
    candidate_key = _normalized_key(candidate)
    return candidate_key == root_key or candidate_key.startswith(root_key + os.sep)


def _validate_raw(raw: str, *, origin: str) -> None:
    if "\x00" in raw:
        raise _fail(ErrorCode.VALIDATION_FAILED, f"{origin} contains a NUL byte.")
    stripped = raw.strip()
    if not stripped:
        raise _fail(ErrorCode.VALIDATION_FAILED, f"{origin} is empty.")
    if stripped in _RESERVED_TARGETS:
        raise _fail(
            ErrorCode.VALIDATION_FAILED,
            f"{origin} must be a filesystem path, not the SQLite special name {stripped!r}.",
        )
    if stripped.lower().startswith("file:"):
        raise _fail(
            ErrorCode.VALIDATION_FAILED,
            f"{origin} must be a plain filesystem path, not a SQLite URI.",
        )


def _resolve(raw: str, root: Path) -> Path:
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        # Relative overrides are anchored at the root, never at the CWD.
        candidate = root / candidate
    # resolve(strict=False) collapses ".." and follows symlinks where possible.
    return Path(os.path.abspath(str(candidate.resolve(strict=False))))


def resolve_db_path(
    root: str | os.PathLike[str],
    *,
    db_path: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    allow_external: bool = False,
) -> ResolvedDBPath:
    """Resolve the runtime database path inside *root*.

    Args:
        root: SERAPHIM root directory (spec §12.1 single root).
        db_path: Explicit override (highest priority).
        environ: Environment mapping; defaults to ``os.environ``.
        allow_external: Permit a path outside the root (documented exception).

    Returns:
        :class:`ResolvedDBPath` with an absolute, symlink-resolved path.

    Raises:
        SeraphimError: ``VALIDATION_FAILED`` for malformed input,
            ``DB_PATH_OUTSIDE_ROOT`` for an override escaping the root.
    """
    env = os.environ if environ is None else environ

    if root is None:
        raise _fail(ErrorCode.VALIDATION_FAILED, "Root directory must not be None.")
    raw_root = os.fspath(root)
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise _fail(ErrorCode.VALIDATION_FAILED, "Root directory must not be empty.")
    _validate_raw(raw_root, origin="Root directory")

    resolved_root = Path(os.path.abspath(str(Path(raw_root).resolve(strict=False))))

    if db_path is not None:
        if not isinstance(db_path, (str, os.PathLike)):
            raise _fail(ErrorCode.VALIDATION_FAILED, "db_path override must be a string or PathLike.")
        raw_value = os.fspath(db_path)
        if not isinstance(raw_value, str):
            raise _fail(ErrorCode.VALIDATION_FAILED, "db_path override must be a string path.")
        _validate_raw(raw_value, origin=f"{DB_PATH_ENV_VAR} override")
        resolved, source = _resolve(raw_value, resolved_root), PathSource.ARGUMENT
    else:
        env_value = env.get(DB_PATH_ENV_VAR)
        if env_value is not None and env_value.strip():
            _validate_raw(env_value, origin=DB_PATH_ENV_VAR)
            resolved, source = _resolve(env_value, resolved_root), PathSource.ENV
        else:
            resolved = _resolve(str(Path(*DEFAULT_DB_RELATIVE_PATH)), resolved_root)
            source = PathSource.DEFAULT

    if not allow_external and not _is_within(resolved_root, resolved):
        raise _fail(
            ErrorCode.DB_PATH_OUTSIDE_ROOT,
            "Database path resolves outside the SERAPHIM root.",
            user_action_required=True,
            details={"source": source},
        )

    if resolved.exists() and resolved.is_dir():
        raise _fail(
            ErrorCode.VALIDATION_FAILED,
            "Resolved database path is a directory, not a file.",
            user_action_required=True,
        )

    return ResolvedDBPath(path=resolved, root=resolved_root, source=source)


def default_db_path(root: str | os.PathLike[str]) -> Path:
    """The default ``<root>/data/seraphim.sqlite`` path, ignoring env overrides."""
    resolved_root = Path(os.path.abspath(str(Path(os.fspath(root)).resolve(strict=False))))
    return _resolve(str(Path(*DEFAULT_DB_RELATIVE_PATH)), resolved_root)
