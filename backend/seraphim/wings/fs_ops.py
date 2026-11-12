# WINGS filesystem operations (S21). Each function takes an FsRoot and a relative path,
# resolves it through the path guard and performs one bounded operation. OS errors are
# normalized to SeraphimError without raw paths or OS messages.

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.wings.fs_paths import (
    COMPONENT,
    FsRoot,
    denied,
    is_link_or_junction,
    is_secret_component,
)

MAX_READ_BYTES = 1_048_576
MAX_WRITE_BYTES = 1_048_576
MAX_LIST_ENTRIES = 500
MAX_SEARCH_FILES = 500
MAX_SEARCH_MATCHES = 200
MAX_LINE_CHARS = 300
TRASH_DIR = "_trash"


def _error(code: str, message: str) -> SeraphimError:
    return SeraphimError(code=code, component=COMPONENT, safe_message=message)


@contextmanager
def _io() -> Iterator[None]:
    try:
        yield
    except SeraphimError:
        raise
    except FileNotFoundError:
        raise _error(ErrorCode.FS_NOT_FOUND, "Path does not exist.") from None
    except FileExistsError:
        raise _error(ErrorCode.FS_CONFLICT, "Target already exists.") from None
    except PermissionError:
        raise _error(ErrorCode.FS_IO_FAILED, "Permission denied by the operating system.") from None
    except OSError:
        raise _error(ErrorCode.FS_IO_FAILED, "Filesystem operation failed.") from None


def _too_large() -> SeraphimError:
    return _error(ErrorCode.FS_TOO_LARGE, "File exceeds the size limit.")


def _require_regular(st: os.stat_result) -> None:
    if is_link_or_junction(st):
        raise denied("Links and junctions are not followed.")
    if not stat.S_ISREG(st.st_mode):
        raise denied("Not a regular file.")


def _require_dir(st: os.stat_result) -> None:
    if is_link_or_junction(st):
        raise denied("Links and junctions are not followed.")
    if not stat.S_ISDIR(st.st_mode):
        raise denied("Not a directory.")


def _require_parent(path: Path) -> Path:
    parent = path.parent
    _require_dir(os.lstat(parent))
    return parent


def _refuse_root(root: FsRoot, path: Path) -> None:
    if os.path.normcase(str(path)) == os.path.normcase(str(root.path)):
        raise denied("The root itself cannot be moved or deleted.")


def _kind(st: os.stat_result) -> str:
    if is_link_or_junction(st):
        return "link"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise _error(ErrorCode.FS_IO_FAILED, "File is not UTF-8 text.") from None


def read_file(root: FsRoot, rel: str) -> dict[str, Any]:
    path = root.resolve(rel)
    with _io():
        before = os.lstat(path)
        _require_regular(before)
        if before.st_size > MAX_READ_BYTES:
            raise _too_large()
        with open(path, "rb") as fh:
            if not os.path.samestat(os.fstat(fh.fileno()), before):
                raise denied("File changed while it was being opened.")
            data = fh.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise _too_large()
    return {"path": rel, "text": _decode(data), "size": len(data)}


def list_dir(root: FsRoot, rel: str) -> dict[str, Any]:
    path = root.resolve(rel)
    entries: list[dict[str, Any]] = []
    truncated = False
    with _io():
        _require_dir(os.lstat(path))
        for name in sorted(os.listdir(path)):
            if is_secret_component(name):
                continue
            if len(entries) >= MAX_LIST_ENTRIES:
                truncated = True
                break
            child = os.lstat(os.path.join(path, name))
            entries.append({"name": name, "kind": _kind(child), "size": child.st_size if _kind(child) == "file" else 0})
    return {"path": rel, "entries": entries, "truncated": truncated}


def search_text(root: FsRoot, rel: str, query: str) -> dict[str, Any]:
    if not query.strip():
        raise _error(ErrorCode.VALIDATION_FAILED, "Query must not be empty.")
    start = root.resolve(rel)
    needle = query.casefold()
    matches: list[dict[str, Any]] = []
    scanned = 0
    skipped = 0
    truncated = False
    stack = [start]
    while stack and not truncated:
        current = stack.pop()
        try:
            st = os.lstat(current)
            if is_link_or_junction(st):
                skipped += 1
                continue
            if stat.S_ISDIR(st.st_mode):
                for name in reversed(sorted(os.listdir(current))):
                    if not is_secret_component(name):
                        stack.append(os.path.join(current, name))
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if scanned >= MAX_SEARCH_FILES:
                truncated = True
                break
            scanned += 1
            if st.st_size > MAX_READ_BYTES:
                skipped += 1
                continue
            with open(current, "rb") as fh:
                data = fh.read(MAX_READ_BYTES + 1)
        except OSError:
            skipped += 1
            continue
        if len(data) > MAX_READ_BYTES or b"\x00" in data:
            skipped += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            skipped += 1
            continue
        rel_path = os.path.relpath(current, root.path).replace("\\", "/")
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.casefold():
                matches.append({"path": rel_path, "line": number, "text": line[:MAX_LINE_CHARS]})
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated = True
                    break
    return {
        "query": query,
        "matches": matches,
        "scanned": scanned,
        "skipped": skipped,
        "truncated": truncated,
    }


def write_file(root: FsRoot, rel: str, text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise _too_large()
    path = root.resolve(rel, must_exist=False)
    with _io():
        parent = _require_parent(path)
        if os.path.lexists(path):
            _require_regular(os.lstat(path))
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".seraphim-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            with suppress(OSError):
                os.remove(tmp)
            raise
    return {"path": rel, "bytes": len(data)}


def create_dir(root: FsRoot, rel: str) -> dict[str, Any]:
    path = root.resolve(rel, must_exist=False)
    with _io():
        _require_parent(path)
        os.mkdir(path)
    return {"path": rel}


def move_path(root: FsRoot, src: str, dst: str) -> dict[str, Any]:
    source = root.resolve(src)
    _refuse_root(root, source)
    target = root.resolve(dst, must_exist=False)
    with _io():
        _require_parent(target)
        if is_link_or_junction(os.lstat(source)):
            raise denied("Links and junctions are not followed.")
        os.rename(source, target)
    return {"from": src, "to": dst}


def delete_path(root: FsRoot, rel: str) -> dict[str, Any]:
    source = root.resolve(rel)
    _refuse_root(root, source)
    trash = root.path / TRASH_DIR
    with _io():
        _require_regular(os.lstat(source))
        if os.path.lexists(trash):
            _require_dir(os.lstat(trash))
        else:
            os.mkdir(trash)
        target = trash / f"{generate_id('file')}-{source.name}"
        os.replace(source, target)
    return {"path": rel, "trashed_to": f"{TRASH_DIR}/{target.name}"}
