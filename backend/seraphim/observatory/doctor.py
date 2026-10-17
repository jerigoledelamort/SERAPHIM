# SERAPHIM OBSERVATORY — read-only diagnostics service (S10).
#
# Spec §4.16 (OBSERVATORY owns diagnostics), §12.4 (`config validate`), §13
# (`seraphim doctor` / `seraphim status`).  CONTRACTS.md §2.18 gives OBSERVATORY
# "diagnostics" and a "read-only audit mode"; this module is that surface.
#
# Design rules:
#   * Read-only.  No check creates a file, applies a migration, writes a log or
#     changes configuration.  A missing database is reported, never created.
#   * No business logic is duplicated: every check calls the owning subsystem's
#     public API (SANCTUM validator / identity loader / secret store, the
#     migration runner).  The CLI and the future GUI call these same functions,
#     so they cannot disagree about what "healthy" means.
#   * No secret material is returned: every payload passes through
#     ``sanitize_dict`` before it leaves this module.
#
# Layer note: CONTRACTS.md §3.1 lists OBSERVATORY at layer 1, and this module
# reads SANCTUM (layer 2) and storage.  The doctor is a read-only *composition
# point* — it aggregates checks, it does not own them — and this deviation from
# the strict layer table is recorded in IMPLEMENTATION_LOG.md (S10) to be
# revisited when CORE/SANCTUM expose a service API (S50).

from __future__ import annotations

import importlib.util
import os
import platform
import socket
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import SeraphimError
from seraphim.contracts.sanitization import sanitize_dict
from seraphim.sanctum.identity import load_identity
from seraphim.sanctum.secrets import create_secret_store
from seraphim.sanctum.validator import ValidationResult, validate_config_files
from seraphim.storage import Database, MigrationRunner

COMPONENT = "observatory.doctor"

#: Check severities.  ``ok`` is healthy, ``warning`` is degraded but usable,
#: ``error`` blocks normal operation and makes the doctor exit non-zero.
OK = "ok"
WARNING = "warning"
ERROR = "error"

_SEVERITY_RANK = {OK: 0, WARNING: 1, ERROR: 2}

#: Root directories from spec §12.2 that this build uses.  A missing directory
#: is a warning, never an error: SERAPHIM applies builtin defaults and creates
#: these directories on first use.
CORE_ROOT_DIRS: tuple[str, ...] = ("config", "identity", "data", "logs")

#: Directories checked for writability when they exist (the runtime writes here).
WRITABLE_ROOT_DIRS: tuple[str, ...] = ("data", "logs")

#: Minimum Python version (mirrors ``requires-python`` in pyproject.toml).
MIN_PYTHON: tuple[int, int] = (3, 11)

#: Modules imported at start-up by the CLI/runtime.
REQUIRED_MODULES: tuple[str, ...] = ("click", "yaml", "sqlite3")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one diagnostic check.

    ``summary`` and ``remediation`` are written for a human reading the CLI
    output: they must be understandable without reading this code.
    """

    id: str
    title: str
    severity: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""

    @property
    def ok(self) -> bool:
        return self.severity == OK

    def to_dict(self) -> dict[str, Any]:
        return sanitize_dict(
            {
                "id": self.id,
                "title": self.title,
                "severity": self.severity,
                "summary": self.summary,
                "remediation": self.remediation,
                "details": self.details,
            }
        )


@dataclass(frozen=True)
class DoctorReport:
    """Full result of :func:`run_doctor`."""

    root: str
    checks: tuple[CheckResult, ...]

    @property
    def errors(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.severity == ERROR)

    @property
    def warnings(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.severity == WARNING)

    @property
    def healthy(self) -> bool:
        """True when no check reported an error (warnings do not block)."""
        return not self.errors

    @property
    def status(self) -> str:
        if self.errors:
            return "error"
        if self.warnings:
            return "degraded"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return sanitize_dict(
            {
                "ok": self.healthy,
                "root": self.root,
                "status": self.status,
                "healthy": self.healthy,
                "error_count": len(self.errors),
                "warning_count": len(self.warnings),
                "checks": [check.to_dict() for check in self.checks],
            }
        )


@dataclass(frozen=True)
class DatabaseSnapshot:
    """Read-only view of the database schema state."""

    path: str
    exists: bool
    initialized: bool
    current_version: int
    head_version: int
    pending: tuple[int, ...]
    out_of_sync: bool
    error_code: str = ""
    events: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_dict(
            {
                "path": self.path,
                "exists": self.exists,
                "initialized": self.initialized,
                "current_version": self.current_version,
                "head_version": self.head_version,
                "pending": list(self.pending),
                "out_of_sync": self.out_of_sync,
                "error_code": self.error_code,
                "events": self.events,
            }
        )


@dataclass(frozen=True)
class StatusReport:
    """Compact system snapshot for ``seraphim status``.

    Reuses the doctor checks for the health verdict and adds a few read-only
    counters (event count, secret references) so a script can poll one command.
    """

    root: str
    status: str
    healthy: bool
    runtime: dict[str, Any]
    config: dict[str, Any]
    database: dict[str, Any]
    secrets: dict[str, Any]
    identity: dict[str, Any]
    checks: tuple[CheckResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return sanitize_dict(
            {
                "ok": self.healthy,
                "root": self.root,
                "status": self.status,
                "healthy": self.healthy,
                "runtime": self.runtime,
                "config": self.config,
                "database": self.database,
                "secrets": self.secrets,
                "identity": self.identity,
                "checks": [check.to_dict() for check in self.checks],
            }
        )


# ---------------------------------------------------------------------------
# Read-only inspectors (shared by doctor and status)
# ---------------------------------------------------------------------------


def _inspect_config(root: Path) -> ValidationResult:
    """Validate configuration through the single SANCTUM entry point."""
    return validate_config_files(root)


def _inspect_database(root: Path, environ: Mapping[str, str] | None) -> DatabaseSnapshot:
    """Inspect the schema state without creating or migrating the database."""
    try:
        db = Database.open(root, environ=environ)
    except SeraphimError as exc:
        return DatabaseSnapshot(
            path="",
            exists=False,
            initialized=False,
            current_version=0,
            head_version=0,
            pending=(),
            out_of_sync=False,
            error_code=exc.code,
        )

    path = str(db.path)
    try:
        runner = MigrationRunner(db)
        schema = runner.status()  # documented as read-only (S05)
    except SeraphimError as exc:
        return DatabaseSnapshot(
            path=path,
            exists=True,
            initialized=False,
            current_version=0,
            head_version=0,
            pending=(),
            out_of_sync=True,
            error_code=exc.code,
        )

    events: int | None = None
    if schema.initialized:
        try:
            events = int(db.scalar("SELECT COUNT(*) AS n FROM events", default=0) or 0)
        except SeraphimError:
            events = None

    return DatabaseSnapshot(
        path=path,
        exists=schema.exists,
        initialized=schema.initialized,
        current_version=schema.current_version,
        head_version=schema.head_version,
        pending=tuple(schema.pending),
        out_of_sync=schema.out_of_sync,
        events=events,
    )


def _inspect_secret_store(root: Path) -> dict[str, Any]:
    """Describe the secret backend without reading any value."""
    try:
        store = create_secret_store(root)
        info = store.info
        try:
            refs = len(store.list_refs())
        except SeraphimError:
            refs = 0
    except SeraphimError as exc:
        return {"backend": "unavailable", "available": False, "references": 0, "error_code": exc.code}
    return {
        "backend": info.backend,
        "available": info.backend != "unavailable",
        "location": info.location,
        "persistent": info.persistent,
        "encrypted_at_rest": info.encrypted_at_rest,
        "references": refs,
    }


def _inspect_identity(root: Path) -> dict[str, Any]:
    """Read the active profile settings (languages/mode), never the layer text."""
    try:
        identity = load_identity(root)
    except SeraphimError as exc:
        return {"valid": False, "error_code": exc.code}
    return {
        "valid": True,
        "ui_language": identity.profile.ui_language,
        "response_language": identity.profile.response_language,
        "default_task_mode": identity.profile.default_task_mode,
        "sources": dict(identity.sources),
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_root(root: Path) -> CheckResult:
    if not root.exists():
        return CheckResult(
            "root",
            "Root directory",
            ERROR,
            "The SERAPHIM root does not exist.",
            details={"path": str(root)},
            remediation="Create the directory or pass the correct root with --config-dir.",
        )
    if not root.is_dir():
        return CheckResult(
            "root",
            "Root directory",
            ERROR,
            "The SERAPHIM root path is not a directory.",
            details={"path": str(root)},
            remediation="Point --config-dir at the SERAPHIM installation directory.",
        )
    return CheckResult(
        "root",
        "Root directory",
        OK,
        "Root directory exists.",
        details={"path": str(root)},
    )


def _check_root_layout(root: Path) -> CheckResult:
    present = [name for name in CORE_ROOT_DIRS if (root / name).is_dir()]
    missing = [name for name in CORE_ROOT_DIRS if name not in present]
    details = {"present": present, "missing": missing, "expected": list(CORE_ROOT_DIRS)}
    if missing:
        return CheckResult(
            "root_layout",
            "Root layout",
            WARNING,
            f"Missing standard directories: {', '.join(missing)}.",
            details=details,
            remediation=(
                "SERAPHIM applies builtin defaults and creates these directories on "
                "first use; create them manually to silence this warning."
            ),
        )
    return CheckResult(
        "root_layout",
        "Root layout",
        OK,
        "Standard directories are present.",
        details=details,
    )


def _check_permissions(root: Path) -> CheckResult:
    if not root.is_dir():
        return CheckResult(
            "permissions",
            "Filesystem permissions",
            ERROR,
            "Cannot check permissions: the root is not an accessible directory.",
            remediation="Fix the root path first (see the 'root' check).",
        )

    problems: list[str] = []
    if not os.access(root, os.R_OK):
        problems.append("root is not readable")
    if not os.access(root, os.W_OK):
        problems.append("root is not writable")
    for name in WRITABLE_ROOT_DIRS:
        directory = root / name
        if directory.is_dir() and not os.access(directory, os.W_OK):
            problems.append(f"{name}/ is not writable")

    details = {"root": str(root), "checked": ["root", *WRITABLE_ROOT_DIRS]}
    if problems:
        return CheckResult(
            "permissions",
            "Filesystem permissions",
            ERROR,
            "; ".join(problems) + ".",
            details=details,
            remediation=(
                "Grant the current user read/write access to the SERAPHIM root and to "
                "its data/ and logs/ directories."
            ),
        )
    return CheckResult(
        "permissions",
        "Filesystem permissions",
        OK,
        "Root is readable and writable.",
        details=details,
    )


def _check_config(root: Path) -> CheckResult:
    result = _inspect_config(root)
    if not result.valid:
        first = result.issues[0]
        return CheckResult(
            "config",
            "Configuration",
            ERROR,
            f"{len(result.issues)} configuration issue(s); first: {first.message}",
            details={"issues": [issue.to_dict() for issue in result.issues]},
            remediation=first.fix
            or "Run 'seraphim config validate' and fix the listed files.",
        )
    return CheckResult("config", "Configuration", OK, "Configuration is valid.")


def _check_database(root: Path, environ: Mapping[str, str] | None) -> CheckResult:
    snapshot = _inspect_database(root, environ)
    details = snapshot.to_dict()

    if snapshot.error_code:
        return CheckResult(
            "database",
            "Database and migrations",
            ERROR,
            f"Database is not usable: {snapshot.error_code}.",
            details=details,
            remediation=(
                "The database file is corrupt, untrusted or unreachable; restore a "
                "valid backup or move the file aside to recreate it."
            ),
        )
    if not snapshot.exists:
        return CheckResult(
            "database",
            "Database and migrations",
            WARNING,
            "Database not initialized yet (no file at the resolved location).",
            details=details,
            remediation="The database is created on first run; no action is required.",
        )
    if not snapshot.initialized:
        return CheckResult(
            "database",
            "Database and migrations",
            ERROR,
            "Database file exists but has no SERAPHIM schema (untrusted database).",
            details=details,
            remediation=(
                "Move the file aside and let SERAPHIM create a fresh database, or "
                "restore a valid backup."
            ),
        )
    if snapshot.current_version > snapshot.head_version:
        return CheckResult(
            "database",
            "Database and migrations",
            ERROR,
            (
                f"Database schema v{snapshot.current_version} is newer than this build "
                f"(v{snapshot.head_version})."
            ),
            details=details,
            remediation="Upgrade SERAPHIM to a build that supports this schema version.",
        )
    if snapshot.pending:
        return CheckResult(
            "database",
            "Database and migrations",
            WARNING,
            f"Pending migrations: {list(snapshot.pending)}.",
            details=details,
            remediation="Apply migrations with the migration tooling before running tasks.",
        )
    return CheckResult(
        "database",
        "Database and migrations",
        OK,
        f"Schema v{snapshot.current_version} is up to date.",
        details=details,
    )


def _check_secret_store(root: Path) -> CheckResult:
    info = _inspect_secret_store(root)
    details = dict(info)
    if not info.get("available", False):
        return CheckResult(
            "secret_store",
            "Secret storage",
            WARNING,
            "No secure secret backend is available on this platform.",
            details=details,
            remediation=(
                "Provider credentials cannot be stored until a secure backend is "
                "available (Windows DPAPI); configuration validation still works."
            ),
        )
    return CheckResult(
        "secret_store",
        "Secret storage",
        OK,
        f"Backend '{info['backend']}' ready ({info.get('references', 0)} reference(s)).",
        details=details,
    )


def _check_identity(root: Path) -> CheckResult:
    info = _inspect_identity(root)
    details = dict(info)
    if not info.get("valid", False):
        return CheckResult(
            "identity",
            "Identity",
            ERROR,
            f"Identity configuration is invalid: {info.get('error_code', 'UNKNOWN')}.",
            details=details,
            remediation="Fix identity/identity.yaml (inspect it with 'seraphim identity show').",
        )
    return CheckResult(
        "identity",
        "Identity",
        OK,
        (
            f"UI language '{info['ui_language']}', response language "
            f"'{info['response_language']}' (builtin defaults where files are missing)."
        ),
        details=details,
    )


def _check_prerequisites() -> CheckResult:
    problems: list[str] = []
    if sys.version_info < MIN_PYTHON:
        problems.append(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"running {platform.python_version()}"
        )
    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    if missing:
        problems.append(f"missing modules: {', '.join(missing)}")

    details = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "min_python": f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}",
        "missing_modules": missing,
    }
    if problems:
        return CheckResult(
            "prerequisites",
            "Runtime prerequisites",
            ERROR,
            "; ".join(problems) + ".",
            details=details,
            remediation=(
                "Install the declared dependencies ('pip install -e .') and use a "
                "supported Python version."
            ),
        )
    return CheckResult(
        "prerequisites",
        "Runtime prerequisites",
        OK,
        f"Python {platform.python_version()} on {platform.system()}; required modules present.",
        details=details,
    )


def _loopback_bindable() -> tuple[bool, str]:
    """Return whether an ephemeral loopback socket can be bound.

    This binds 127.0.0.1 on an ephemeral port and closes it immediately: it is a
    transient probe, not a persistent listener, so it changes no state.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
    except OSError as exc:
        return False, exc.strerror or str(exc)
    finally:
        sock.close()
    return True, ""


def _check_local_api() -> CheckResult:
    # The GUI<->CORE loopback API is scheduled for S50; this build has no server.
    bindable, reason = _loopback_bindable()
    details = {"implemented": False, "loopback_bindable": bindable}
    if not bindable:
        return CheckResult(
            "local_api",
            "Local API",
            WARNING,
            f"Loopback binding is unavailable: {reason}.",
            details=details,
            remediation="The GUI<->CORE loopback API cannot bind on this host.",
        )
    return CheckResult(
        "local_api",
        "Local API",
        WARNING,
        "Loopback API is not implemented in this build (arrives with VESSEL, S50).",
        details=details,
        remediation="No action required; the CLI works without the local API.",
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_doctor(
    root: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> DoctorReport:
    """Run every read-only check against *root*.

    Args:
        root: SERAPHIM root directory.
        environ: Environment mapping used for database path resolution;
            defaults to ``os.environ``.

    Returns:
        A :class:`DoctorReport`.  Errors make ``report.healthy`` False; warnings
        keep it True.
    """
    root_path = Path(root)
    checks = (
        _check_root(root_path),
        _check_root_layout(root_path),
        _check_permissions(root_path),
        _check_config(root_path),
        _check_database(root_path, environ),
        _check_secret_store(root_path),
        _check_identity(root_path),
        _check_prerequisites(),
        _check_local_api(),
    )
    return DoctorReport(root=str(root_path), checks=checks)


def build_status(
    root: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> StatusReport:
    """Build a compact, read-only system snapshot (``seraphim status``)."""
    root_path = Path(root)
    report = run_doctor(root_path, environ=environ)
    config = _inspect_config(root_path)
    return StatusReport(
        root=str(root_path),
        status=report.status,
        healthy=report.healthy,
        runtime={"python": platform.python_version(), "platform": platform.system()},
        config={"valid": config.valid, "issues": len(config.issues)},
        database=_inspect_database(root_path, environ).to_dict(),
        secrets=_inspect_secret_store(root_path),
        identity=_inspect_identity(root_path),
        checks=report.checks,
    )
