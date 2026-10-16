# SERAPHIM test configuration.
#
# Hard isolation rule for S05 and everything that touches storage:
# no test may read or write a real user database.  The guard below (a) pins
# SERAPHIM_DB_PATH to a throwaway directory so any accidental path resolution
# lands in tmp, and (b) fails the session if a SQLite file appears in the
# repository's own ``data/`` directory while tests run.

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session", autouse=True)
def _never_touch_user_database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    quarantine = tmp_path_factory.mktemp("seraphim-db-quarantine")
    previous = os.environ.get("SERAPHIM_DB_PATH")
    os.environ["SERAPHIM_DB_PATH"] = str(quarantine / "data" / "seraphim.sqlite")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SERAPHIM_DB_PATH", None)
        else:
            os.environ["SERAPHIM_DB_PATH"] = previous

    leftovers = sorted(p.name for p in (REPO_ROOT / "data").glob("*.sqlite*")) if (
        REPO_ROOT / "data"
    ).exists() else []
    if leftovers:
        pytest.fail(
            "Test run created files in the repository data/ directory: "
            f"{leftovers}. Tests must use a temporary database only."
        )


@pytest.fixture(autouse=True)
def _isolated_known_secrets() -> Iterator[None]:
    """Clear the process-wide known-secret registry around every test.

    The secret store registers every value it reads so that the value can never
    be written back to a log, error or export (S09).  That registry is
    process-wide state, so tests must not leak it into one another.
    """
    from seraphim.contracts.sanitization import clear_known_secrets

    clear_known_secrets()
    try:
        yield
    finally:
        clear_known_secrets()


@pytest.fixture
def test_root(tmp_path: Path) -> Path:
    """A throwaway SERAPHIM root (never user data)."""
    return tmp_path / "seraphim-root"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """An environment mapping with SERAPHIM_DB_PATH removed."""
    monkeypatch.delenv("SERAPHIM_DB_PATH", raising=False)
    return {}


@pytest.fixture
def db(test_root: Path):
    """A migrated Database handle bound to a temporary root."""
    from seraphim.storage import Database, MigrationRunner

    handle = Database.open(test_root, environ={})
    MigrationRunner(handle).run()
    return handle


@pytest.fixture
def raw_connection(db):
    """A plain sqlite3 connection to the test database for low-level asserts."""
    connection = sqlite3.connect(str(db.path))
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()
