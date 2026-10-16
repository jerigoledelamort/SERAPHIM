# SERAPHIM OBSERVATORY — EventStore tests (S06).
# Acceptance: events survive restart, payload serialization, query by task/session/type.

import tempfile
from pathlib import Path

import pytest
from seraphim.contracts.events import Event
from seraphim.contracts.sanitization import register_known_secret
from seraphim.observatory.store import EventStore
from seraphim.storage.db import Database


@pytest.fixture
def temp_db() -> Database:
    """Create temporary database with schema."""
    # Create temporary file-based database
    tmp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp_path = Path(tmp_file.name)
    tmp_file.close()

    db = Database(tmp_path)

    # Create events table directly (matches m0001_kernel schema)
    db.execute("""
        CREATE TABLE events (
            id             TEXT PRIMARY KEY,
            timestamp      TEXT    NOT NULL,
            type           TEXT    NOT NULL,
            component      TEXT    NOT NULL,
            severity       TEXT    NOT NULL DEFAULT 'INFO',
            task_id        TEXT    NOT NULL DEFAULT '',
            session_id     TEXT    NOT NULL DEFAULT '',
            correlation_id TEXT    NOT NULL DEFAULT '',
            payload_json   TEXT    NOT NULL DEFAULT '{}',
            schema_version INTEGER NOT NULL DEFAULT 1
        )
    """)

    yield db

    # Cleanup
    tmp_path.unlink(missing_ok=True)


def test_store_save_and_load_by_id(temp_db: Database) -> None:
    """Test save event and load by ID."""
    store = EventStore(temp_db)
    event = Event(
        type="task.created",
        component="test",
        severity="INFO",
        task_id="t123",
        payload={"action": "create", "count": 1},
    )

    store.save(event)

    # Load back
    loaded = store.load_by_id(event.id)
    assert loaded is not None
    assert loaded.id == event.id
    assert loaded.type == "task.created"
    assert loaded.component == "test"
    assert loaded.task_id == "t123"
    assert loaded.payload == {"action": "create", "count": 1}


def test_store_load_by_id_not_found(temp_db: Database) -> None:
    """Test load_by_id returns None for missing event."""
    store = EventStore(temp_db)
    result = store.load_by_id("event_nonexistent")
    assert result is None


def test_store_load_by_task(temp_db: Database) -> None:
    """Test load events by task_id."""
    store = EventStore(temp_db)

    # Create events for task_123
    for i in range(3):
        event = Event(
            type="task.step",
            component="test",
            task_id="task_123",
            payload={"step": i},
        )
        store.save(event)

    # Create event for different task
    other = Event(type="task.step", component="test", task_id="task_456")
    store.save(other)

    # Query task_123
    results = store.load_by_task("task_123")
    assert len(results) == 3
    assert all(e.task_id == "task_123" for e in results)


def test_store_load_by_session(temp_db: Database) -> None:
    """Test load events by session_id."""
    store = EventStore(temp_db)

    # Create events for session_A
    for i in range(2):
        event = Event(
            type="session.event",
            component="test",
            session_id="session_A",
            payload={"index": i},
        )
        store.save(event)

    # Create event for session_B
    other = Event(type="session.event", component="test", session_id="session_B")
    store.save(other)

    results = store.load_by_session("session_A")
    assert len(results) == 2
    assert all(e.session_id == "session_A" for e in results)


def test_store_load_by_type(temp_db: Database) -> None:
    """Test load events by type."""
    store = EventStore(temp_db)

    # Create task.created events
    for i in range(2):
        store.save(Event(type="task.created", component="test", payload={"n": i}))

    # Create different type
    store.save(Event(type="tool.call.started", component="test"))

    results = store.load_by_type("task.created")
    assert len(results) == 2
    assert all(e.type == "task.created" for e in results)


def test_store_count_by_task(temp_db: Database) -> None:
    """Test count events for a task."""
    store = EventStore(temp_db)

    for _ in range(5):
        store.save(Event(type="task.event", component="test", task_id="t999"))

    count = store.count_by_task("t999")
    assert count == 5

    count_empty = store.count_by_task("t_nonexistent")
    assert count_empty == 0


def test_store_payload_serialization(temp_db: Database) -> None:
    """Test complex payload JSON serialization."""
    store = EventStore(temp_db)

    complex_payload = {
        "nested": {"key": "value", "list": [1, 2, 3]},
        "number": 42,
        "boolean": True,
        "null": None,
    }

    event = Event(
        type="test.complex",
        component="test",
        payload=complex_payload,
    )

    store.save(event)
    loaded = store.load_by_id(event.id)

    assert loaded is not None
    assert loaded.payload == complex_payload


def test_store_event_survives_restart(temp_db: Database) -> None:
    """CRITICAL: Event persisted in DB survives 'restart'.

    Acceptance criterion: event history survives restart.
    """
    store = EventStore(temp_db)

    # Save event
    event = Event(
        type="system.startup",
        component="CORE",
        severity="INFO",
        task_id="t_restart_test",
        payload={"message": "System started"},
    )
    store.save(event)

    # Simulate restart: create new EventStore with same DB
    store2 = EventStore(temp_db)

    # Load event — must still exist
    loaded = store2.load_by_id(event.id)
    assert loaded is not None, "Event did not survive restart!"
    assert loaded.type == "system.startup"
    assert loaded.task_id == "t_restart_test"
    assert loaded.payload == {"message": "System started"}


def test_store_empty_payload(temp_db: Database) -> None:
    """Test event with empty payload."""
    store = EventStore(temp_db)

    event = Event(type="simple.event", component="test", payload={})
    store.save(event)

    loaded = store.load_by_id(event.id)
    assert loaded is not None
    assert loaded.payload == {}


def test_store_optional_fields(temp_db: Database) -> None:
    """Test event with only required fields."""
    store = EventStore(temp_db)

    event = Event(type="minimal.event", component="test")
    store.save(event)

    loaded = store.load_by_id(event.id)
    assert loaded is not None
    assert loaded.type == "minimal.event"
    assert loaded.component == "test"
    assert loaded.task_id == ""
    assert loaded.session_id == ""
    assert loaded.correlation_id == ""


def test_store_correlation_id(temp_db: Database) -> None:
    """Test correlation_id preserved."""
    store = EventStore(temp_db)

    event = Event(
        type="test.correlated",
        component="test",
        correlation_id="corr_abc123",
    )
    store.save(event)

    loaded = store.load_by_id(event.id)
    assert loaded is not None
    assert loaded.correlation_id == "corr_abc123"


def test_store_ordering_by_timestamp(temp_db: Database) -> None:
    """Test events returned in DESC timestamp order."""
    store = EventStore(temp_db)

    # Create events with auto-generated timestamps
    # (later events have later timestamps)
    events = []
    for i in range(3):
        e = Event(type="test.order", component="test", task_id="t_order", payload={"seq": i})
        store.save(e)
        events.append(e)

    # Load by task — should be DESC order (newest first)
    loaded = store.load_by_task("t_order")
    assert len(loaded) == 3
    # Check that first loaded is last created
    assert loaded[0].payload["seq"] == 2
    assert loaded[1].payload["seq"] == 1
    assert loaded[2].payload["seq"] == 0


def test_store_sanitizes_payload_at_write_boundary(temp_db: Database) -> None:
    """S09: a payload mutated after construction is still scrubbed on save.

    ``Event.__post_init__`` scrubs the payload, but the dict is mutable, so the
    write boundary must sanitize too — otherwise a secret could reach SQLite.
    """
    marker = "SERAPHIM_TEST_SECRET_xyz789"
    register_known_secret(marker)
    store = EventStore(temp_db)

    event = Event(type="test.mutated", component="test", payload={"note": "clean"})
    event.payload["leaked"] = marker
    event.payload["api_key"] = marker
    store.save(event)

    rows = temp_db.query("SELECT payload_json FROM events WHERE id = ?", (event.id,))
    stored = rows[0]["payload_json"]
    assert marker not in stored
    assert "[REDACTED]" in stored


def test_store_sanitizes_pattern_secret_at_write_boundary(temp_db: Database) -> None:
    """A provider-format key never reaches SQLite, even without registration."""
    literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
    store = EventStore(temp_db)

    event = Event(type="test.pattern", component="test", payload={"note": "clean"})
    event.payload["leaked"] = literal
    store.save(event)

    rows = temp_db.query("SELECT payload_json FROM events WHERE id = ?", (event.id,))
    assert literal not in rows[0]["payload_json"]
