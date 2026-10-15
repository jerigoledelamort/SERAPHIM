# SERAPHIM storage — migration registry (S05).
#
# Append new steps to ``MIGRATIONS`` in ``runner.py``; never edit an applied
# migration (its checksum is verified on every run).

from __future__ import annotations

from seraphim.storage.migrations.base import AppliedMigration, Migration
from seraphim.storage.migrations.runner import (
    BOOTSTRAP_TABLE,
    MIGRATIONS,
    MigrationReport,
    MigrationRunner,
    SchemaStatus,
)

__all__ = [
    "BOOTSTRAP_TABLE",
    "MIGRATIONS",
    "AppliedMigration",
    "Migration",
    "MigrationReport",
    "MigrationRunner",
    "SchemaStatus",
]
