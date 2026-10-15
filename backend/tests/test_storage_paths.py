# S05 — database path resolution inside the SERAPHIM root.

from __future__ import annotations

import os
from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.storage.paths import (
    DB_PATH_ENV_VAR,
    DEFAULT_DB_RELATIVE_PATH,
    PathSource,
    default_db_path,
    resolve_db_path,
)


def test_default_path_is_inside_root(test_root: Path) -> None:
    resolved = resolve_db_path(test_root, environ={})
    assert resolved.source == PathSource.DEFAULT
    assert resolved.path == (test_root / Path(*DEFAULT_DB_RELATIVE_PATH)).resolve()
    assert resolved.path.is_absolute()


def test_resolution_does_not_create_anything(test_root: Path) -> None:
    resolve_db_path(test_root, environ={})
    assert not test_root.exists()


def test_env_var_overrides_default(test_root: Path) -> None:
    resolved = resolve_db_path(test_root, environ={DB_PATH_ENV_VAR: "private/state.sqlite"})
    assert resolved.source == PathSource.ENV
    assert resolved.path == (test_root / "private" / "state.sqlite").resolve()


def test_argument_beats_env_var(test_root: Path) -> None:
    resolved = resolve_db_path(
        test_root,
        db_path="data/other.sqlite",
        environ={DB_PATH_ENV_VAR: "data/from-env.sqlite"},
    )
    assert resolved.source == PathSource.ARGUMENT
    assert resolved.path.name == "other.sqlite"


def test_relative_override_is_anchored_at_root_not_cwd(
    test_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    resolved = resolve_db_path(test_root, db_path="data/db.sqlite", environ={})
    assert resolved.path.parent == (test_root / "data").resolve()
    assert elsewhere not in resolved.path.parents


def test_dotdot_cannot_escape_root(test_root: Path) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(test_root, db_path="data/../../outside.sqlite", environ={})
    assert excinfo.value.code == ErrorCode.DB_PATH_OUTSIDE_ROOT


def test_absolute_path_outside_root_is_rejected(tmp_path: Path, test_root: Path) -> None:
    outside = (tmp_path / "elsewhere" / "seraphim.sqlite").resolve()
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(test_root, db_path=str(outside), environ={})
    assert excinfo.value.code == ErrorCode.DB_PATH_OUTSIDE_ROOT
    assert excinfo.value.user_action_required is True


def test_absolute_path_outside_root_allowed_by_explicit_flag(
    tmp_path: Path, test_root: Path
) -> None:
    outside = (tmp_path / "elsewhere" / "seraphim.sqlite").resolve()
    resolved = resolve_db_path(test_root, db_path=str(outside), environ={}, allow_external=True)
    assert resolved.path == outside


def test_case_insensitive_containment_on_windows(test_root: Path) -> None:
    (test_root / "data").mkdir(parents=True)
    (test_root / "data" / "seraphim.sqlite").write_bytes(b"")
    upper = str(test_root / "DATA" / "seraphim.sqlite")
    resolved = resolve_db_path(test_root, db_path=upper, environ={})
    assert resolved.path.name.lower() == "seraphim.sqlite"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        ":memory:",
        ":temp:",
        "file:test.db?mode=ro",
        "FILE:test.db",
        "data\x00/db.sqlite",
    ],
)
def test_malformed_override_is_rejected(test_root: Path, bad: str) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(test_root, db_path=bad, environ={})
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


def test_non_string_override_is_rejected(test_root: Path) -> None:
    with pytest.raises(SeraphimError):
        resolve_db_path(test_root, db_path=123, environ={})  # type: ignore[arg-type]


def test_directory_as_db_path_is_rejected(test_root: Path) -> None:
    (test_root / "data" / "folder").mkdir(parents=True)
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(test_root, db_path="data/folder", environ={})
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("bad_root", ["", "   ", None])
def test_invalid_root_is_rejected(bad_root: object) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(bad_root, environ={})  # type: ignore[arg-type]
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


def test_empty_env_value_falls_back_to_default(test_root: Path) -> None:
    resolved = resolve_db_path(test_root, environ={DB_PATH_ENV_VAR: "  "})
    assert resolved.source == PathSource.DEFAULT


def test_default_db_path_ignores_env(test_root: Path) -> None:
    assert default_db_path(test_root) == (test_root / "data" / "seraphim.sqlite").resolve()


def test_env_var_is_ignored_by_default_db_path(test_root: Path) -> None:
    expected = (test_root / "data" / "seraphim.sqlite").resolve()
    os.environ.pop(DB_PATH_ENV_VAR, None)
    assert default_db_path(test_root) == expected


def test_symlink_escape_is_rejected(test_root: Path, tmp_path: Path) -> None:
    (test_root / "data").mkdir(parents=True)
    link = test_root / "data" / "link.sqlite"
    try:
        os.symlink(str(tmp_path / "outside.sqlite"), str(link), target_is_directory=False)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privileges on this Windows configuration")
    with pytest.raises(SeraphimError) as excinfo:
        resolve_db_path(test_root, db_path="data/link.sqlite", environ={})
    assert excinfo.value.code == ErrorCode.DB_PATH_OUTSIDE_ROOT
