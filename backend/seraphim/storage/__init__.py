# SERAPHIM storage — SQLite persistence and schema migrations (S05).
#
# Layer: sits below OBSERVATORY/REGISTRY and depends only on CONTRACTS
# (CONTRACTS.md §3.1).  Nothing else in this package may import it upward.
#
# Public surface:
#   Database          — connection/query helper, parameterized statements only
#   MigrationRunner   — transactional, idempotent schema migration
#   resolve_db_path   — path inside the SERAPHIM root + test override

from __future__ import annotations

from seraphim.storage.db import Database, guard_sql, normalize_params, validate_identifier
from seraphim.storage.migrations import (
    BOOTSTRAP_TABLE,
    MIGRATIONS,
    AppliedMigration,
    Migration,
    MigrationReport,
    MigrationRunner,
    SchemaStatus,
)
from seraphim.storage.paths import (
    DB_PATH_ENV_VAR,
    DEFAULT_DB_RELATIVE_PATH,
    PathSource,
    ResolvedDBPath,
    default_db_path,
    resolve_db_path,
)

__all__ = [
    "BOOTSTRAP_TABLE",
    "DB_PATH_ENV_VAR",
    "DEFAULT_DB_RELATIVE_PATH",
    "MIGRATIONS",
    "AppliedMigration",
    "Database",
    "Migration",
    "MigrationReport",
    "MigrationRunner",
    "PathSource",
    "ResolvedDBPath",
    "SchemaStatus",
    "default_db_path",
    "guard_sql",
    "normalize_params",
    "resolve_db_path",
    "validate_identifier",
]
