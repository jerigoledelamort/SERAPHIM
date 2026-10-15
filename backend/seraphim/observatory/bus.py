# SERAPHIM OBSERVATORY — event bus with subscriber isolation (S06).
# Spec §3.1, §4.16: pub/sub, crash doesn't break execution.

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.events import Event

# Subscriber callback signature.
EventSubscriber = Callable[[Event], None]

logger = logging.getLogger(__name__)


class EventBus:
    """Event bus with subscriber failure isolation.

    Features:
    - Multiple subscribers per event type
    - Wildcard subscriptions via "*"
    - Subscriber errors don't crash publisher or other subscribers
    - Order guarantee: subscribers called in registration order within type
    """

    def __init__(self) -> None:
        # event_type → list of subscribers (in registration order)
        self._subscribers: dict[str, list[EventSubscriber]] = defaultdict(list)
        # subscriber → failed call count (for circuit breaker tracking)
        self._failures: dict[EventSubscriber, int] = defaultdict(int)
        self._max_failures = 3  # After 3 consecutive fails, subscriber is muted

    def subscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Register a subscriber for the given event type.

        Use "*" to subscribe to all event types.
        Subscriber is called in registration order with other subscribers for the same type.
        """
        if not callable(subscriber):
            msg = f"Subscriber must be callable, got {type(subscriber).__name__}"
            raise TypeError(msg)
        if not event_type:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="observatory.bus",
                safe_message="Event type must not be empty",
            )
        self._subscribers[event_type].append(subscriber)
        logger.debug(f"Subscribed {subscriber.__name__} to {event_type}")

    def publish(self, event: Event) -> None:
        """Publish event to all subscribers.

        Subscribers are called in registration order.
        Subscriber errors are logged but don't crash the publish call or affect other subscribers.
        After max_failures consecutive errors, subscriber is muted (no longer called).
        """
        if not isinstance(event, Event):
            msg = f"Event must be Event instance, got {type(event).__name__}"
            raise TypeError(msg)

        # Collect subscribers: specific type + wildcard
        subscribers = self._subscribers.get(event.type, []) + self._subscribers.get("*", [])

        for sub in subscribers:
            # Skip muted subscribers
            if self._failures[sub] >= self._max_failures:
                continue

            try:
                sub(event)
                # Reset failure count on success
                if sub in self._failures:
                    del self._failures[sub]
            except Exception as exc:
                self._failures[sub] += 1
                failure_count = self._failures[sub]
                logger.error(
                    f"Subscriber {sub.__name__} failed on {event.type} "
                    f"({failure_count}/{self._max_failures}): {exc}",
                    exc_info=True,
                )
                if failure_count >= self._max_failures:
                    logger.warning(f"Subscriber {sub.__name__} muted after {failure_count} failures")

    def unsubscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Remove a subscriber from the given event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(subscriber)
                logger.debug(f"Unsubscribed {subscriber.__name__} from {event_type}")
            except ValueError:
                pass  # Already not subscribed
        if subscriber in self._failures:
            del self._failures[subscriber]

    def clear(self) -> None:
        """Remove all subscribers (for testing)."""
        self._subscribers.clear()
        self._failures.clear()

    def subscriber_count(self, event_type: str | None = None) -> int:
        """Return subscriber count for event_type (or total if None)."""
        if event_type is None:
            return sum(len(subs) for subs in self._subscribers.values())
        return len(self._subscribers.get(event_type, []))
