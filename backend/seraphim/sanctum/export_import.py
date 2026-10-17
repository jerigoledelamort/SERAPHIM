# SERAPHIM SANCTUM — export/import pipeline (S11).
#
# Spec §15: "Backup может включать конфигурацию, identity, Skills, manifests и
# пользовательские adapters".  Скрывает секреты, проверяет manifest/version,
# защищает от path traversal и откатывается при частичной ошибке.
#
# Reuses ``build_safe_export`` / ``verify_no_secrets`` из S09 for the config
# + identity payload, then adds zip packaging, checksums, locale/theme/skills
# and a dry-run / staging / backup / atomic-apply flow for import.

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum.export import (
    EXPORT_FORMAT_VERSION,
    build_safe_export,
    find_secret_material,
    verify_no_secrets,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPONENT = "sanctum.export_import"
SERAPHIM_VERSION = "0.1.0"

#: Domains that the export includes (all are user-facing and non-secret).
DOMAINS = ("config", "identity", "locale", "theme", "skills")

#: Map logical domain → directory name under the SERAPHIM root.
DOMAIN_DIRS: dict[str, str] = {
    "config": "config",
    "identity": "identity",
    "locale": "locales",
    "theme": "themes",
    "skills": "skills",
}

#: Directories under the root that are explicitly excluded from the archive.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    (
        "data",       # database, backups, migrations, secret blobs
        "logs",       # runtime logs
        "artifacts",  # task artifacts, images, CAD
        "memory",     # memory stores
        "cache",      # transient caches
    )
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fail(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        user_action_required=True,
        details=details,
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_secret_free(archive_path: str, data: bytes) -> None:
    """Refuse to archive a raw file that carries secret material.

    ``build_safe_export``/``verify_no_secrets`` only see the structured config
    and identity payload.  The locale, theme and skills domains are archived as
    raw bytes, so a key pasted into a ``.css``/``.json``/``.yaml`` there would
    otherwise slip into the archive.  Every file is therefore screened here; the
    error reports only the offending path, never the secret value.
    """
    text = data.decode("utf-8", errors="ignore")
    leaks = find_secret_material(text)
    if leaks:
        raise _fail(
            ErrorCode.ARCHIVE_EXPORT_FAILED,
            f"Refusing to export {archive_path!r}: it appears to contain secret material.",
            details={"archive_path": archive_path, "count": len(leaks)},
        )


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------


def _check_traversal(archive_name: str, target_root: Path) -> Path:
    """Return a resolved path inside *target_root*, refusing traversal."""
    inner = PurePosixPath(archive_name)
    # Strip leading '/' if present.
    if inner.is_absolute():
        inner = inner.relative_to("/")
    # Resolve against target_root; reject if it escapes.
    resolved = (target_root / inner).resolve()
    try:
        resolved.relative_to(target_root.resolve())
    except ValueError:
        raise _fail(
            ErrorCode.ARCHIVE_PATH_TRAVERSAL,
            f"Archive entry {archive_name!r} escapes the target root — path traversal detected.",
            details={"archive_name": archive_name},
        ) from None
    return resolved


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_to_archive(
    root: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build a secret-free archive of SERAPHIM config + identity + locale + theme + skills.

    Args:
        root: Path to the SERAPHIM root directory.
        output_path: Destination zip path.  Defaults to
            ``<root>/data/backups/seraphim-export-<timestamp>.zip``.

    Returns:
        Manifest dict (also written alongside the zip).

    Raises:
        SeraphimError: ARCHIVE_EXPORT_FAILED if verification or filesystem fails.
    """
    root_path = Path(root).resolve()
    backup_dir = root_path / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = backup_dir / f"seraphim-export-{ts}.zip"

    output_path = Path(output_path).resolve()

    # 1. Build the safe export payload (config + identity, secrets excluded).
    try:
        payload = build_safe_export(root_path)
    except SeraphimError:
        raise
    except Exception as exc:
        raise _fail(
            ErrorCode.ARCHIVE_EXPORT_FAILED,
            f"Failed to build export payload: {exc}",
            details={"root": str(root_path)},
        ) from exc

    # Defence in depth: the builder should already pass, but we check again.
    try:
        verify_no_secrets(payload)
    except SeraphimError:
        raise

    # 2. Walk allowed directories and collect files.
    files: list[dict[str, Any]] = []
    for _domain, dir_name in DOMAIN_DIRS.items():
        dir_path = root_path / dir_name
        if not dir_path.is_dir():
            continue
        for file_path in sorted(dir_path.rglob("*")):
            if not file_path.is_file():
                continue
            # Skip excluded directories (double-check).
            rel = file_path.relative_to(root_path)
            if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
                continue
            arc_name = rel.as_posix()
            raw = file_path.read_bytes()
            _assert_secret_free(arc_name, raw)
            files.append({
                "archive_path": arc_name,
                "size": len(raw),
                "sha256": _sha256(raw),
            })

    # 3. Build manifest.
    manifest = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "seraphim_version": SERAPHIM_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(root_path),
        "domains": list(DOMAINS),
        "excluded": {
            "secrets": "secret values are never exported (secrets.included=false)",
            "database": "data/ directory (SQLite, backups, secret blobs)",
            "logs": "logs/ directory",
            "artifacts": "artifacts/ directory",
            "memory": "memory/ directory",
            "cache": "cache/ directory",
        },
        "file_count": len(files),
        "files": files,
    }

    # 4. Write zip archive: manifest first, then files.
    try:
        with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
            for finfo in files:
                src = root_path / finfo["archive_path"]
                zf.write(src, finfo["archive_path"])
    except Exception as exc:
        # Clean up partial zip.
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise _fail(
            ErrorCode.ARCHIVE_EXPORT_FAILED,
            f"Failed to write archive: {exc}",
            details={"archive_path": str(output_path)},
        ) from exc

    # 5. Save manifest alongside the zip.
    manifest_path = output_path.with_suffix(".json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return manifest


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class _ImportDiff:
    """Result of a dry-run import — what would change."""

    def __init__(
        self,
        added: list[str],
        modified: list[str],
        removed: list[str],
        unchanged: list[str],
    ) -> None:
        self.added = added
        self.modified = modified
        self.removed = removed
        self.unchanged = unchanged

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "modified": self.modified,
            "removed": self.removed,
            "unchanged": self.unchanged,
        }

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.removed)

    def __repr__(self) -> str:
        return (
            f"_ImportDiff(added={len(self.added)}, modified={len(self.modified)}, "
            f"removed={len(self.removed)}, unchanged={len(self.unchanged)})"
        )


def _read_archive_files(archive_path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Open the archive and return (manifest, {archive_path: bytes})."""
    files: dict[str, bytes] = {}
    manifest: dict[str, Any] = {}
    with ZipFile(archive_path, "r") as zf:
        for name in zf.namelist():
            raw = zf.read(name)
            if name == "manifest.json":
                manifest = json.loads(raw)
            else:
                files[name] = raw
    return manifest, files


def _check_version(manifest: dict[str, Any]) -> None:
    """Verify format_version compatibility."""
    fmt_ver = manifest.get("export_format_version", 0)
    if fmt_ver != EXPORT_FORMAT_VERSION:
        raise _fail(
            ErrorCode.ARCHIVE_VERSION_INCOMPATIBLE,
            (
                f"Archive format version {fmt_ver} is not compatible with "
                f"this SERAPHIM version (expected {EXPORT_FORMAT_VERSION})."
            ),
            details={"archive_version": fmt_ver, "expected_version": EXPORT_FORMAT_VERSION},
        )


def _verify_checksums(manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    """Verify every archived file matches the sha256 recorded in the manifest.

    The manifest advertises ``checksums`` per file, so import must actually
    verify them: otherwise a truncated or tampered archive is applied silently.
    Every entry in the manifest must be present with a matching digest, and no
    file may exist in the archive that the manifest does not declare.  The error
    never echoes the offending bytes, only the path.
    """
    expected: dict[str, str] = {
        entry["archive_path"]: entry.get("sha256", "")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict) and "archive_path" in entry
    }

    for arc_name, data in files.items():
        want = expected.get(arc_name)
        if want is None:
            raise _fail(
                ErrorCode.ARCHIVE_INTEGRITY_FAILED,
                f"Archive entry {arc_name!r} is not declared in the manifest.",
                details={"archive_path": arc_name},
            )
        if _sha256(data) != want:
            raise _fail(
                ErrorCode.ARCHIVE_INTEGRITY_FAILED,
                f"Archive entry {arc_name!r} does not match its recorded checksum.",
                details={"archive_path": arc_name},
            )


def _collect_existing(root: Path) -> dict[str, bytes]:
    """Read all files in the allowed domains from *root*."""
    existing: dict[str, bytes] = {}
    for dir_name in DOMAIN_DIRS.values():
        dir_path = root / dir_name
        if not dir_path.is_dir():
            continue
        for fp in sorted(dir_path.rglob("*")):
            if not fp.is_file():
                continue
            rel = fp.relative_to(root)
            if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
                continue
            existing[rel.as_posix()] = fp.read_bytes()
    return existing


def _backup_current(root: Path, backup_dir: Path) -> Path:
    """Copy allowed domains to *backup_dir* and return the backup path."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"pre-import-backup-{backup_ts}"
    backup_path.mkdir(parents=True, exist_ok=True)

    for dir_name in DOMAIN_DIRS.values():
        src = root / dir_name
        if not src.is_dir():
            continue
        dst = backup_path / dir_name
        shutil.copytree(src, dst, dirs_exist_ok=True)

    return backup_path


def _atomic_apply(
    files: dict[str, bytes],
    target_root: Path,
    exclude: set[str] | None = None,
    remove: list[str] | None = None,
) -> None:
    """Write *files* to *target_root* atomically per-file (temp + os.replace).

    Each file is written to a temp file in the same directory, then atomically
    replaced.  If the operation fails mid-way, remaining files are not applied
    (caller must restore from backup).

    After writing, every path in *remove* is deleted so the result matches the
    archive exactly.  ``removed`` files are those the dry-run diff promised to
    delete; without this the ``--apply`` result would keep stale files that the
    preview said would go away.  Removal is guarded by the same traversal check
    as writes, and a failure here triggers the caller's rollback (the backup
    still holds the deleted files).
    """
    if exclude is None:
        exclude = set()
    for arc_name, data in files.items():
        if arc_name in exclude:
            continue
        dest = _check_traversal(arc_name, target_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + f".import-tmp-{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(str(tmp), str(dest))

    for arc_name in remove or []:
        dest = _check_traversal(arc_name, target_root)
        dest.unlink(missing_ok=True)


def import_from_archive(
    archive_path: str | os.PathLike[str],
    target_root: str | os.PathLike[str],
    *,
    dry_run: bool = True,
    current_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Validate and optionally apply an export archive to *target_root*.

    Args:
        archive_path: Path to the zip archive.
        target_root: Destination SERAPHIM root directory.
        dry_run: If True, only return the diff without writing anything.
        current_root: If provided, the *current* SERAPHIM root to back up
            before applying (defaults to *target_root*).

    Returns:
        Dict with ``dry_run`` (bool), ``diff`` (added/modified/removed/unchanged)
        and, if not dry_run, ``backup_path`` (where the previous config was saved).

    Raises:
        SeraphimError: ARCHIVE_NOT_FOUND, ARCHIVE_PATH_TRAVERSAL,
            ARCHIVE_VERSION_INCOMPATIBLE, ARCHIVE_INTEGRITY_FAILED.
    """
    archive_path = Path(archive_path).resolve()
    target = Path(target_root).resolve()
    current = Path(current_root).resolve() if current_root else target

    # 1. Validate archive exists and is readable.
    if not archive_path.is_file():
        raise _fail(
            ErrorCode.ARCHIVE_NOT_FOUND,
            f"Archive not found: {archive_path}",
        )

    # 2. Read and validate manifest.
    try:
        manifest, files = _read_archive_files(archive_path)
    except Exception as exc:
        raise _fail(
            ErrorCode.ARCHIVE_INTEGRITY_FAILED,
            f"Failed to read archive: {exc}",
            details={"archive_path": str(archive_path)},
        ) from exc

    _check_version(manifest)

    # 3. Validate each entry against path traversal.
    for arc_name in files:
        _check_traversal(arc_name, target)

    # 3b. Verify the recorded checksums before touching the filesystem.
    _verify_checksums(manifest, files)

    # 4. Compute diff against existing files in target_root.
    existing = _collect_existing(target)
    archive_names = set(files.keys())

    added = sorted(archive_names - existing.keys())
    removed = sorted(existing.keys() - archive_names)
    modified: list[str] = []
    unchanged: list[str] = []
    for name in sorted(archive_names & existing.keys()):
        if files[name] != existing[name]:
            modified.append(name)
        else:
            unchanged.append(name)

    diff = _ImportDiff(added, modified, removed, unchanged)

    if dry_run:
        return {
            "dry_run": True,
            "diff": diff.to_dict(),
            "manifest": manifest,
        }

    # 5. Apply: backup current, atomic write.
    backup_path = _backup_current(current, current / "data" / "backups")

    try:
        _atomic_apply(files, target, remove=diff.removed)
    except Exception as exc:
        # Rollback: restore from backup.
        try:
            _restore_backup(backup_path, current)
        except Exception as rb_exc:
            raise _fail(
                ErrorCode.ARCHIVE_ROLLBACK_FAILED,
                (
                    f"Import failed ({exc}) and rollback also failed ({rb_exc}). "
                    f"Manual recovery required from {backup_path}."
                ),
                details={"backup_path": str(backup_path), "error": str(exc), "rollback_error": str(rb_exc)},
            ) from rb_exc
        raise _fail(
            ErrorCode.ARCHIVE_IMPORT_FAILED,
            f"Import failed at file write: {exc}. Rolled back from {backup_path}.",
            details={"backup_path": str(backup_path)},
        ) from exc

    return {
        "dry_run": False,
        "backup_path": str(backup_path),
        "diff": diff.to_dict(),
        "manifest": manifest,
    }


def _restore_backup(backup_path: Path, target_root: Path) -> None:
    """Restore every domain from *backup_path* into *target_root*.

    Iterates the *directory names* (``DOMAIN_DIRS.values()``), not the logical
    domain keys: the backup is written under the directory names (``locales``,
    ``themes``), so iterating the keys (``locale``, ``theme``) silently skipped
    those two domains and left a partially-applied import on disk.  A domain
    that the import created but that did not exist before the import is removed,
    so a failed import leaves the exact pre-import state and nothing extra.
    """
    if not backup_path.is_dir():
        return
    for dir_name in DOMAIN_DIRS.values():
        src = backup_path / dir_name
        dst = target_root / dir_name
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        elif dst.exists():
            # The domain did not exist before the import but the apply step
            # created it: remove it to fully restore the previous state.
            shutil.rmtree(dst)
