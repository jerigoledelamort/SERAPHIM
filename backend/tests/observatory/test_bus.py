# SERAPHIM OBSERVATORY — EventBus tests (S06).
# Acceptance: subscriber failure isolation, order guarantees, wildcard.

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event
from seraphim.observatory.bus import EventBus


def test_bus_subscribe_and_publish() -> None:
    """Test basic subscribe/publish flow."""
    bus = EventBus()
    received = []

    def handler(event: Event) -> None:
        received.append(event.type)

    bus.subscribe("task.created", handler)
    event = Event(type="task.created", component="test")
    bus.publish(event)

    assert received == ["task.created"]


def test_bus_multiple_subscribers_same_type() -> None:
    """Test multiple subscribers for same event type called in order."""
    bus = EventBus()
    call_order = []

    def handler1(event: Event) -> None:
        call_order.append("h1")

    def handler2(event: Event) -> None:
        call_order.append("h2")

    def handler3(event: Event) -> None:
        call_order.append("h3")

    bus.subscribe("task.created", handler1)
    bus.subscribe("task.created", handler2)
    bus.subscribe("task.created", handler3)

    event = Event(type="task.created", component="test")
    bus.publish(event)

    assert call_order == ["h1", "h2", "h3"]


def test_bus_wildcard_subscriber() -> None:
    """Test wildcard subscription receives all event types."""
    bus = EventBus()
    received = []

    def wildcard_handler(event: Event) -> None:
        received.append(event.type)

    bus.subscribe("*", wildcard_handler)

    bus.publish(Event(type="task.created", component="test"))
    bus.publish(Event(type="tool.call.started", component="test"))
    bus.publish(Event(type="error.occurred", component="test"))

    assert received == ["task.created", "tool.call.started", "error.occurred"]


def test_bus_specific_and_wildcard() -> None:
    """Test specific + wildcard subscribers both called."""
    bus = EventBus()
    calls = []

    def specific(event: Event) -> None:
        calls.append(("specific", event.type))

    def wildcard(event: Event) -> None:
        calls.append(("wildcard", event.type))

    bus.subscribe("task.created", specific)
    bus.subscribe("*", wildcard)

    bus.publish(Event(type="task.created", component="test"))

    assert calls == [("specific", "task.created"), ("wildcard", "task.created")]


def test_bus_subscriber_failure_isolation() -> None:
    """CRITICAL: subscriber exception doesn't crash publish or affect other subscribers."""
    bus = EventBus()
    calls = []

    def handler1(event: Event) -> None:
        calls.append("h1")

    def handler_crash(event: Event) -> None:
        calls.append("crash")
        raise RuntimeError("Subscriber crash")

    def handler3(event: Event) -> None:
        calls.append("h3")

    bus.subscribe("task.created", handler1)
    bus.subscribe("task.created", handler_crash)
    bus.subscribe("task.created", handler3)

    event = Event(type="task.created", component="test")
    bus.publish(event)  # Should not raise

    assert calls == ["h1", "crash", "h3"]


def test_bus_circuit_breaker_after_max_failures() -> None:
    """Test subscriber muted after max_failures consecutive errors."""
    bus = EventBus()
    call_count = 0

    def failing_handler(event: Event) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Always fails")

    bus.subscribe("task.created", failing_handler)

    for _ in range(5):
        bus.publish(Event(type="task.created", component="test"))

    # Should be called exactly 3 times (max_failures), then muted
    assert call_count == 3


def test_bus_circuit_breaker_reset_on_success() -> None:
    """Test failure counter resets after successful call."""
    bus = EventBus()
    call_count = 0
    should_fail = True

    def flaky_handler(event: Event) -> None:
        nonlocal call_count
        call_count += 1
        if should_fail:
            raise ValueError("Intermittent failure")

    bus.subscribe("task.created", flaky_handler)

    # Fail twice
    for _ in range(2):
        bus.publish(Event(type="task.created", component="test"))

    # Now succeed
    should_fail = False
    bus.publish(Event(type="task.created", component="test"))

    # Fail again — counter should be reset, so still callable
    should_fail = True
    bus.publish(Event(type="task.created", component="test"))

    # Should have been called 4 times total (not muted after first 2 failures because of reset)
    assert call_count == 4


def test_bus_unsubscribe() -> None:
    """Test unsubscribe removes subscriber."""
    bus = EventBus()
    received = []

    def handler(event: Event) -> None:
        received.append(event.type)

    bus.subscribe("task.created", handler)
    bus.publish(Event(type="task.created", component="test"))
    assert len(received) == 1

    bus.unsubscribe("task.created", handler)
    bus.publish(Event(type="task.created", component="test"))
    assert len(received) == 1  # Not called second time


def test_bus_clear() -> None:
    """Test clear removes all subscribers."""
    bus = EventBus()
    received = []

    def handler(event: Event) -> None:
        received.append(event.type)

    bus.subscribe("task.created", handler)
    bus.subscribe("*", handler)

    bus.clear()

    bus.publish(Event(type="task.created", component="test"))
    assert received == []


def test_bus_subscriber_count() -> None:
    """Test subscriber_count returns correct counts."""
    bus = EventBus()

    def handler1(event: Event) -> None:
        pass

    def handler2(event: Event) -> None:
        pass

    assert bus.subscriber_count() == 0
    assert bus.subscriber_count("task.created") == 0

    bus.subscribe("task.created", handler1)
    assert bus.subscriber_count() == 1
    assert bus.subscriber_count("task.created") == 1

    bus.subscribe("task.created", handler2)
    assert bus.subscriber_count() == 2
    assert bus.subscriber_count("task.created") == 2

    bus.subscribe("tool.call.started", handler1)
    assert bus.subscriber_count() == 3
    assert bus.subscriber_count("task.created") == 2
    assert bus.subscriber_count("tool.call.started") == 1


def test_bus_validate_subscriber_callable() -> None:
    """Test subscribe rejects non-callable."""
    bus = EventBus()
    with pytest.raises(TypeError, match="Subscriber must be callable"):
        bus.subscribe("task.created", "not_callable")  # type: ignore


def test_bus_validate_event_type_not_empty() -> None:
    """Test subscribe rejects empty event type."""
    bus = EventBus()

    def handler(event: Event) -> None:
        pass

    with pytest.raises(SeraphimError) as exc_info:
        bus.subscribe("", handler)
    assert exc_info.value.code == ErrorCode.VALIDATION_FAILED


def test_bus_publish_validates_event_instance() -> None:
    """Test publish rejects non-Event objects."""
    bus = EventBus()
    with pytest.raises(TypeError, match="Event must be Event instance"):
        bus.publish({"type": "fake"})  # type: ignore
