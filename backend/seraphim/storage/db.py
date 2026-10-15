# SERAPHIM storage — SQLite access layer (S05).
#
# Design rules enforced here:
#   * Every value reaches SQLite through bound parameters (``?`` / ``:name``).
#     SQL text is never built from user data; identifiers used by the generic
#     helpers are validated against a strict allow-list.
#   * Transactions are explicit.  ``sqlite3``'s implicit "BEGIN before DML"
#     behaviour is disabled (``isolation_level=None``) so that DDL and DML share
#     one predictable transaction boundary — SQLite DDL is transactional and a
#     failed migration can be rolled back completely.
#   * ``executescript`` is never used inside a transaction because it issues an
#     implicit COMMIT; migrations therefore ship as tuples of single statements.

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.storage.paths import ResolvedDBPath, resolve_db_path

COMPONENT = "storage.db"

# Identifiers accepted by the generic helpers (tables/columns).
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# SQL placeholders supported by sqlite3 (qmark and named styles).
_PLACEHOLDER_RE = re.compile(r"\?(?!\w)|:\w+")

# Templates that indicate someone tried to interpolate values into SQL text.
_INTERPOLATION_RES = (
    re.compile(r"%s|%\([^)]*\)s"),  # printf-style
    re.compile(r"\{\d+\}"),  # str.format positional
    re.compile(r"\{[a-zA-Z_]\w*\}"),  # str.format / f-string named
)

# Values SQLite can bind without an adapter.  Anything else must be serialized
# by the caller — silent ``str()`` coercion would corrupt round-trips.
_SUPPORTED_VALUE_TYPES = (type(None), int, float, str, bytes)

# SQLite keywords that must never be used as a bare table/column name.
_RESERVED_IDENTIFIERS = frozenset(
    {
        "select",
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "table",
        "index",
        "from",
        "where",
        "order",
        "group",
        "pragma",
        "attach",
        "detach",
    }
)


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


def _wrap_sqlite_error(exc: sqlite3.Error, action: str) -> SeraphimError:
    """Map a sqlite3 failure to a structured error without leaking paths/secrets."""
    message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    lowered = message.lower()
    if "unable to open database file" in lowered or "unable to open" in lowered:
        code, retry, user_action = ErrorCode.DB_UNAVAILABLE, True, True
    elif "not a database" in lowered or "file is not a database" in lowered:
        code, retry, user_action = ErrorCode.DB_INTEGRITY_FAILED, False, True
    elif "database is locked" in lowered or "readonly database" in lowered:
        code, retry, user_action = ErrorCode.DB_UNAVAILABLE, True, True
    elif isinstance(exc, sqlite3.IntegrityError):
        code, retry, user_action = ErrorCode.VALIDATION_FAILED, False, False
    elif isinstance(exc, (sqlite3.OperationalError, sqlite3.ProgrammingError)):
        # "no such table", syntax errors, multi-statement misuse — the SQL or
        # the schema state is wrong, not the storage device.
        code, retry, user_action = ErrorCode.QUERY_INVALID, False, False
    else:
        code, retry, user_action = ErrorCode.DB_UNAVAILABLE, True, False
    return _fail(
        code,
        f"{action} failed: {type(exc).__name__}",
        retryable=retry,
        user_action_required=user_action,
        details={"reason": message[:200]},
    )


def validate_identifier(name: str, *, kind: str = "identifier") -> str:
    """Validate a table/column identifier against a strict allow-list."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise _fail(
            ErrorCode.QUERY_INVALID,
            f"Illegal {kind} name: only [a-z_][a-z0-9_]* is allowed.",
            user_action_required=True,
            details={"kind": kind},
        )
    if name in _RESERVED_IDENTIFIERS:
        raise _fail(
            ErrorCode.QUERY_INVALID,
            f"Reserved SQL keyword cannot be used as a {kind} name.",
            user_action_required=True,
            details={"kind": kind},
        )
    return name


def _check_bind_value(value: Any) -> Any:
    if isinstance(value, bool):  # bool is an int subclass; bind as 0/1 explicitly.
        return int(value)
    if isinstance(value, _SUPPORTED_VALUE_TYPES):
        return value
    raise _fail(
        ErrorCode.QUERY_INVALID,
        f"Unsupported bind value type {type(value).__name__}; serialize it first.",
        details={"value_type": type(value).__name__},
    )


def normalize_params(params: Any) -> Any:
    """Validate and normalize bind parameters to a tuple or dict."""
    if params is None:
        return ()
    if isinstance(params, Mapping):
        return {validate_identifier(k, kind="parameter name"): _check_bind_value(v) for k, v in params.items()}
    if isinstance(params, (bytes, str)):
        raise _fail(
            ErrorCode.QUERY_INVALID,
            "Bind parameters must be a sequence or mapping, not a bare string.",
        )
    if isinstance(params, Sequence):
        return tuple(_check_bind_value(v) for v in params)
    raise _fail(
        ErrorCode.QUERY_INVALID,
        f"Bind parameters must be a sequence or mapping, got {type(params).__name__}.",
    )


def guard_sql(sql: str, params: Any) -> tuple[str, Any]:
    """Validate SQL text + bind parameters before touching the driver.

    Rejects multi-statement strings, template interpolation markers and any
    mismatch between placeholders and supplied parameters, so that a missing
    parameter can never degrade into a silently interpolated literal.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise _fail(ErrorCode.QUERY_INVALID, "SQL statement must be a non-empty string.")
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise _fail(ErrorCode.QUERY_INVALID, "SQL statement must be a non-empty string.")
    if ";" in statement:
        raise _fail(
            ErrorCode.QUERY_INVALID,
            "Multi-statement SQL is not allowed; execute one statement per call.",
            user_action_required=True,
        )
    for pattern in _INTERPOLATION_RES:
        if pattern.search(statement):
            raise _fail(
                ErrorCode.QUERY_INVALID,
                "SQL text contains an interpolation marker; bind values with ? or :name.",
                user_action_required=True,
            )

    normalized = normalize_params(params)
    has_placeholders = _PLACEHOLDER_RE.search(statement) is not None
    supplied = len(normalized)
    if has_placeholders and supplied == 0:
        raise _fail(
            ErrorCode.QUERY_INVALID,
            "SQL contains placeholders but no bind parameters were supplied.",
            user_action_required=True,
        )
    if not has_placeholders and supplied > 0:
        raise _fail(
            ErrorCode.QUERY_INVALID,
            "Bind parameters supplied but SQL contains no placeholders.",
            user_action_required=True,
        )
    return statement, normalized


@dataclass(frozen=True)
class Database:
    """A handle to one SQLite file inside (or explicitly outside) the root."""

    path: Path
    timeout: float = 30.0
    journal_mode: str = "WAL"
    _resolved: ResolvedDBPath | None = field(default=None, compare=False, repr=False)

    # -- Construction ---------------------------------------------------------

    @classmethod
    def open(
        cls,
        root: str | os.PathLike[str],
        *,
        db_path: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
        allow_external: bool = False,
        timeout: float = 30.0,
    ) -> Database:
        """Resolve the database path inside *root* and return a handle."""
        resolved = resolve_db_path(
            root,
            db_path=db_path,
            environ=environ,
            allow_external=allow_external,
        )
        return cls(path=resolved.path, timeout=timeout, _resolved=resolved)

    # -- Connections ----------------------------------------------------------

    _ALLOWED_JOURNAL_MODES = frozenset(
        {"WAL", "DELETE", "TRUNCATE", "MEMORY", "OFFLINE", "PERSIST"}
    )
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured connection in explicit-transaction mode."""
        connection = self._raw_connect()
        try:
            yield connection
        finally:
            connection.close()

    def _raw_connect(self) -> sqlite3.Connection:
        self._ensure_parent_dir()
        try:
            connection = sqlite3.connect(
                str(self.path),
                timeout=self.timeout,
                isolation_level=None,  # Manual BEGIN/COMMIT — transactional DDL works.
            )
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise _wrap_sqlite_error(exc, "connect") from exc
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            # PRAGMA values cannot be bound; int() guarantees a numeric literal.
            connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
            jm = self.journal_mode.upper()
            if jm not in self._ALLOWED_JOURNAL_MODES:
                raise _fail(ErrorCode.VALIDATION_FAILED, f"Invalid journal_mode: {self.journal_mode}")
            connection.execute(f"PRAGMA journal_mode = {jm}")
            # Force the driver to actually read the header: a corrupt or
            # non-database file must fail here, not on the first business query.
            connection.execute("PRAGMA user_version").fetchone()
        except sqlite3.Error as exc:
            connection.close()
            raise _wrap_sqlite_error(exc, "open database") from exc
        return connection

    def _ensure_parent_dir(self) -> None:
        parent = self.path.parent
        if str(parent) and not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise _fail(
                    ErrorCode.DB_UNAVAILABLE,
                    "Cannot create the database directory.",
                    retryable=True,
                    user_action_required=True,
                ) from exc

    @contextmanager
    def transaction(self, mode: str = "IMMEDIATE") -> Iterator[sqlite3.Connection]:
        """Explicit transaction: COMMIT on success, full ROLLBACK on any error."""
        if mode.upper() not in ("DEFERRED", "IMMEDIATE", "EXCLUSIVE"):
            raise _fail(ErrorCode.QUERY_INVALID, f"Unknown transaction mode: {mode}")
        connection = self._raw_connect()
        try:
            connection.execute(f"BEGIN {mode.upper()}")
            try:
                yield connection
            except BaseException:
                self._safe_rollback(connection)
                raise
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            self._safe_rollback(connection)
            raise _wrap_sqlite_error(exc, "transaction") from exc
        finally:
            connection.close()

    @staticmethod
    def _safe_rollback(connection: sqlite3.Connection) -> None:
        try:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
        except sqlite3.Error:
            # The transaction is already gone (e.g. driver rolled back on error).
            pass

    # -- Query helpers --------------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Any = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> sqlite3.Cursor:
        """Execute one parameterized statement (own transaction when no connection)."""
        statement, normalized = guard_sql(sql, params)
        if connection is not None:
            try:
                return connection.execute(statement, normalized)
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "execute") from exc
        with self.transaction() as own:
            try:
                cursor = own.execute(statement, normalized)
                cursor.fetchall()  # Drain so the cursor cannot hold the write lock.
                return cursor
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "execute") from exc

    def executemany(
        self,
        sql: str,
        seq_of_params: Sequence[Sequence[Any]],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        """Execute one parameterized statement for many parameter rows."""
        statement, _ = guard_sql(sql, (None,))
        if isinstance(seq_of_params, (str, bytes)) or not isinstance(seq_of_params, Sequence):
            raise _fail(ErrorCode.QUERY_INVALID, "executemany needs a sequence of parameter rows.")
        rows = [normalize_params(row) for row in seq_of_params]
        if rows:
            arity = len(rows[0])
            if any(len(row) != arity for row in rows):
                raise _fail(ErrorCode.QUERY_INVALID, "executemany rows must have equal arity.")
        if connection is not None:
            try:
                return int(connection.executemany(statement, rows).rowcount)
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "executemany") from exc
        with self.transaction() as own:
            try:
                return int(own.executemany(statement, rows).rowcount)
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "executemany") from exc

    def query(
        self,
        sql: str,
        params: Any = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Run a parameterized SELECT and return rows as dicts."""
        statement, normalized = guard_sql(sql, params)
        if connection is not None:
            try:
                return [dict(row) for row in connection.execute(statement, normalized).fetchall()]
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "query") from exc
        with self.connect() as own:
            try:
                return [dict(row) for row in own.execute(statement, normalized).fetchall()]
            except sqlite3.Error as exc:
                raise _wrap_sqlite_error(exc, "query") from exc

    def query_one(
        self,
        sql: str,
        params: Any = (),
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        rows = self.query(sql, params, connection=connection)
        return rows[0] if rows else None

    def scalar(
        self,
        sql: str,
        params: Any = (),
        *,
        default: Any = None,
        connection: sqlite3.Connection | None = None,
    ) -> Any:
        row = self.query_one(sql, params, connection=connection)
        if not row:
            return default
        return next(iter(row.values()))

    def insert_row(
        self,
        table: str,
        row: Mapping[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        """INSERT one row using validated identifiers and bound parameters only."""
        if not row:
            raise _fail(ErrorCode.QUERY_INVALID, "insert_row requires at least one column.")
        validated_table = validate_identifier(table, kind="table")
        columns = [validate_identifier(c, kind="column") for c in row]
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {validated_table} ({', '.join(columns)}) VALUES ({placeholders})"
        values = tuple(row[c] for c in columns)
        cursor = self.execute(sql, values, connection=connection)
        return int(cursor.lastrowid or 0)

    # -- Introspection --------------------------------------------------------

    def table_names(self, *, connection: sqlite3.Connection | None = None) -> set[str]:
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ?",
            ("table", "sqlite_%"),
            connection=connection,
        )
        return {str(row["name"]) for row in rows}

    def quick_check(self) -> bool:
        """SQLite integrity_check shortcut used by doctor-style diagnostics."""
        with self.connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"

    def file_exists(self) -> bool:
        return self.path.exists()
