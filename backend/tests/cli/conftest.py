"""Shared fixtures for S10 CLI tests (doctor, status, logs, config).

Every test runs against an isolated SERAPHIM root with an empty HOME so that no
real user configuration (~/.config/seraphim) or database is ever touched.  The
database path is pinned inside the throwaway root (a file that is never created)
so the doctor/status database check is deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def s10_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated SERAPHIM root with empty HOME and a pinned DB path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    root = tmp_path / "seraphim-root"
    (root / "config").mkdir(parents=True)

    # Pin the DB inside the root so it resolves to a non-existent file (a
    # warning, never an error) and never touches the repository or quarantine.
    monkeypatch.setenv("SERAPHIM_DB_PATH", str(root / "data" / "seraphim.sqlite"))
    return root
