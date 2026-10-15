# S05 — SQLite access layer: parameterization discipline, transactions, errors.

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.storage import Database, guard_sql, validate_identifier


def make_db(tmp_path: Path) -> Database:
    return Database(path=tmp_path / "nested" / "state.sqlite")


# -- Path handling in the handle itself ---------------------------------------


def test_connect_creates_parent_directories(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    db.execute("CREATE TABLE t (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
    assert db.path.exists()
    assert db.path.parent.is_dir()


def test_corrupt_file_is_reported_not_silently_accepted(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    db.path.parent.mkdir(parents=True)
    db.path.write_bytes(b"this is definitely not a sqlite database file" * 4)
    with pytest.raises(SeraphimError) as excinfo:
        db.query("SELECT 1")
    assert excinfo.value.code == ErrorCode.DB_INTEGRITY_FAILED
    assert excinfo.value.user_action_required is True


def test_directory_as_database_is_reported(tmp_path: Path) -> None:
    db = Database(path=tmp_path / "folder")
    db.path.mkdir()
    with pytest.raises(SeraphimError):
        db.query("SELECT 1")


# -- Parameterization discipline ----------------------------------------------


def test_values_never_enter_sql_text(db: Database) -> None:
    db.insert_row(
        "sessions",
        {"id": "session_1", "title": "'; DROP TABLE tasks; --", "created_at": "t", "updated_at": "t"},
    )
    row = db.query_one("SELECT title FROM sessions WHERE id = ?", ("session_1",))
    assert row is not None and row["title"] == "'; DROP TABLE tasks; --"
    assert "tasks" in db.table_names()


def test_multi_statement_sql_is_refused(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.execute("CREATE TABLE a (x INTEGER); DROP TABLE tasks")
    assert excinfo.value.code == ErrorCode.QUERY_INVALID
    assert "tasks" in db.table_names()


def test_interpolation_templates_are_refused(db: Database) -> None:
    for sql in (
        "SELECT * FROM sessions WHERE id = %s",
        "SELECT * FROM sessions WHERE id = {sid}",
        "SELECT * FROM sessions WHERE id = {0}",
    ):
        with pytest.raises(SeraphimError) as excinfo:
            db.query(sql, ("x",))
        assert excinfo.value.code == ErrorCode.QUERY_INVALID


def test_placeholder_without_params_is_refused(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.query("SELECT * FROM sessions WHERE id = ?")
    assert excinfo.value.code == ErrorCode.QUERY_INVALID


def test_params_without_placeholder_is_refused(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.query("SELECT * FROM sessions", ("x",))
    assert excinfo.value.code == ErrorCode.QUERY_INVALID


def test_like_wildcard_is_a_parameter_not_sql(db: Database) -> None:
    db.insert_row("sessions", {"id": "session_a", "title": "alpha", "created_at": "t", "updated_at": "t"})
    rows = db.query("SELECT id FROM sessions WHERE title LIKE ?", ("%alph%",))
    assert [r["id"] for r in rows] == ["session_a"]


def test_unsupported_bind_type_is_rejected(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.query("SELECT * FROM sessions WHERE id = ?", ({"nested": 1},))
    assert excinfo.value.code == ErrorCode.QUERY_INVALID


def test_bool_binds_as_integer(db: Database) -> None:
    db.execute("CREATE TABLE flags (id TEXT PRIMARY KEY, on_off INTEGER NOT NULL)")
    db.insert_row("flags", {"id": "f", "on_off": True})
    assert db.scalar("SELECT on_off FROM flags WHERE id = ?", ("f",)) == 1


def test_named_parameters_are_supported(db: Database) -> None:
    db.insert_row("sessions", {"id": "s1", "title": "x", "created_at": "t", "updated_at": "t"})
    row = db.query_one("SELECT title FROM sessions WHERE id = :wanted", {"wanted": "s1"})
    assert row is not None and row["title"] == "x"


@pytest.mark.parametrize(
    "bad", ["Select", "1table", "table;DROP", "ok table", "table-name", "", "SELECT", "drop"]
)
def test_identifier_allow_list(bad: str) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        validate_identifier(bad, kind="table")
    assert excinfo.value.code == ErrorCode.QUERY_INVALID


def test_guard_sql_strips_trailing_semicolon() -> None:
    statement, params = guard_sql("SELECT 1 FROM sessions WHERE id = ? ; ", ("a",))
    assert statement == "SELECT 1 FROM sessions WHERE id = ?"
    assert params == ("a",)


# -- CRUD and integrity -------------------------------------------------------


def test_insert_query_round_trip(db: Database) -> None:
    now = "2026-10-14T00:00:00.000Z"
    db.insert_row("tasks", {"id": "task_1", "goal": "проверить кириллицу", "status": "DRAFT", "created_at": now, "updated_at": now})
    row = db.query_one("SELECT goal, status FROM tasks WHERE id = ?", ("task_1",))
    assert row == {"goal": "проверить кириллицу", "status": "DRAFT"}


def test_primary_key_conflict_maps_to_validation_error(db: Database) -> None:
    payload = {"id": "task_1", "goal": "g", "status": "DRAFT", "created_at": "t", "updated_at": "t"}
    db.insert_row("tasks", payload)
    with pytest.raises(SeraphimError) as excinfo:
        db.insert_row("tasks", payload)
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


def test_foreign_keys_are_enforced(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.insert_row(
            "tasks",
            {
                "id": "task_1",
                "session_id": "session_missing",
                "goal": "g",
                "status": "DRAFT",
                "created_at": "t",
                "updated_at": "t",
            },
        )
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


def test_unique_index_is_enforced(db: Database) -> None:
    base = {"kind": "skill", "name": "alpha", "registered_at": "t", "updated_at": "t"}
    db.insert_row("components", {"id": "component_1", **base})
    with pytest.raises(SeraphimError) as excinfo:
        db.insert_row("components", {"id": "component_2", **base})
    assert excinfo.value.code == ErrorCode.VALIDATION_FAILED


def test_executemany_inserts_all_rows(db: Database) -> None:
    rows = [(f"session_{i}", f"title {i}", "t", "t") for i in range(25)]
    count = db.executemany(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        rows,
    )
    assert count == 25
    assert db.scalar("SELECT COUNT(*) FROM sessions") == 25


def test_executemany_rejects_ragged_rows(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.executemany(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            [("a", "b", "t", "t"), ("c", "d", "t")],
        )
    assert excinfo.value.code == ErrorCode.QUERY_INVALID


# -- Transactions -------------------------------------------------------------


def test_transaction_rolls_back_everything_on_error(db: Database) -> None:
    db.insert_row("sessions", {"id": "session_keep", "title": "keep", "created_at": "t", "updated_at": "t"})
    with pytest.raises(RuntimeError), db.transaction() as connection:
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("session_gone", "gone", "t", "t"),
        )
        raise RuntimeError("boom")
    ids = {row["id"] for row in db.query("SELECT id FROM sessions")}
    assert ids == {"session_keep"}


def test_transaction_commits_on_success(db: Database) -> None:
    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("session_ok", "ok", "t", "t"),
        )
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE id = ?", ("session_ok",)) == 1


def test_transaction_sees_no_partial_state_after_rollback(db: Database) -> None:
    with pytest.raises(ValueError), db.transaction() as connection:
        connection.execute("CREATE TABLE ephemeral (id TEXT PRIMARY KEY)")
        raise ValueError("abort")
    assert "ephemeral" not in db.table_names()


def test_unknown_transaction_mode_is_refused(db: Database) -> None:
    with pytest.raises(SeraphimError), db.transaction("SNAPSHOT"):
        pass


def test_connection_is_closed_even_on_error(db: Database) -> None:
    captured: list[sqlite3.Connection] = []
    with pytest.raises(RuntimeError), db.connect() as connection:
        captured.append(connection)
        connection.execute("SELECT 1")
        raise RuntimeError("boom")
    assert captured
    with pytest.raises(sqlite3.ProgrammingError):
        captured[0].execute("SELECT 1")


def test_quick_check_passes_on_migrated_db(db: Database) -> None:
    assert db.quick_check() is True


def test_error_details_do_not_leak_database_path(db: Database) -> None:
    with pytest.raises(SeraphimError) as excinfo:
        db.query("SELECT * FROM no_such_table")
    diagnostic = excinfo.value.to_diagnostic_dict()
    assert str(db.path) not in str(diagnostic)
