# SERAPHIM OBSERVATORY — log tailing service (S10).
#
# Spec §4.16: OBSERVATORY owns structured logs; §13 lists `seraphim logs tail`.
# CONTRACTS.md §2.18 / TB-7: a log line may quote untrusted input, so every line
# is redacted before it is returned.  Reading is read-only: no file is created
# or rotated here (rotation is a later OBSERVATORY stage).
#
# Symlinks are skipped so a link planted in logs/ cannot be used to read a file
# outside the root.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_text

COMPONENT = "observatory.logs"

LOG_DIR_NAME = "logs"
DEFAULT_TAIL_LINES = 50

#: How many bytes to read from the end of a file.  Keeps a huge log from being
#: loaded in full while still returning the requested tail.
MAX_TAIL_BYTES = 1_048_576  # 1 MiB


def _fail(code: str, message: str, *, details: dict[str, object] | None = None) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        user_action_required=True,
        details=details,
    )


@dataclass(frozen=True)
class LogTail:
    """Result of reading the tail of a log file."""

    root: str
    log_dir: str
    files: tuple[str, ...]
    selected: str
    lines: tuple[str, ...]
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "log_dir": self.log_dir,
            "files": list(self.files),
            "selected": self.selected,
            "lines": list(self.lines),
            "truncated": self.truncated,
        }


def _log_files(log_dir: Path) -> list[Path]:
    """Return non-hidden, non-symlink regular files under *log_dir*."""
    if not log_dir.is_dir():
        return []
    found: list[Path] = []
    for path in log_dir.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(log_dir).parts):
            continue
        found.append(path)
    return sorted(found)


def _relative(path: Path, log_dir: Path) -> str:
    return path.relative_to(log_dir).as_posix()


def _tail_lines(path: Path, count: int) -> tuple[list[str], bool]:
    """Return the last *count* lines and whether the file was truncated."""
    if count <= 0:
        return [], path.stat().st_size > 0
    size = path.stat().st_size
    truncated = size > MAX_TAIL_BYTES
    with open(path, "rb") as handle:
        if truncated:
            handle.seek(size - MAX_TAIL_BYTES)
            handle.readline()  # drop the partial first line
        data = handle.read()
    text = data.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    if len(lines) > count:
        truncated = True
        lines = lines[-count:]
    return lines, truncated


def read_log_tail(
    root: str | os.PathLike[str],
    *,
    lines: int = DEFAULT_TAIL_LINES,
    name: str | None = None,
) -> LogTail:
    """Read the tail of a log file under ``<root>/logs``.

    Args:
        root: SERAPHIM root directory.
        lines: How many trailing lines to return (0 = none).
        name: A log file name (relative path or basename).  When omitted, the
            most recently modified log file is used.

    Returns:
        A :class:`LogTail` with redacted lines.

    Raises:
        SeraphimError: ``VALIDATION_FAILED`` for a negative line count,
            ``LOG_FILE_NOT_FOUND`` when *name* does not match a log file.
    """
    if lines < 0:
        raise _fail(ErrorCode.VALIDATION_FAILED, "--lines must be zero or greater.")

    root_path = Path(root)
    log_dir = root_path / LOG_DIR_NAME
    files = _log_files(log_dir)
    rel_files = tuple(_relative(path, log_dir) for path in files)

    if name is not None:
        matches = [
            path
            for path in files
            if _relative(path, log_dir) == name or path.name == name
        ]
        if not matches:
            raise _fail(
                ErrorCode.LOG_FILE_NOT_FOUND,
                f"No log file matches '{name}' under {LOG_DIR_NAME}/.",
                details={"available": list(rel_files)},
            )
        selected = matches[0]
    elif files:
        selected = max(files, key=lambda path: path.stat().st_mtime)
    else:
        selected = None

    if selected is None:
        return LogTail(
            root=str(root_path),
            log_dir=str(log_dir),
            files=rel_files,
            selected="",
            lines=(),
            truncated=False,
        )

    raw_lines, truncated = _tail_lines(selected, lines)
    return LogTail(
        root=str(root_path),
        log_dir=str(log_dir),
        files=rel_files,
        selected=_relative(selected, log_dir),
        lines=tuple(sanitize_text(line) for line in raw_lines),
        truncated=truncated,
    )
