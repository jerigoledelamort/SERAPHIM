# SERAPHIM MODEL LAYER — cooperative cancellation (S12).
#
# Cancellation is cooperative: the provider polls the token between units of
# work.  A cancelled request raises a normalized PROVIDER_CANCELLED error, so
# CORE can distinguish "user stopped this" from a failure.

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from seraphim.model_layer.errors import provider_cancelled_error

#: Poll interval (seconds) used by :func:`run_with_cancellation`.  Small enough
#: that a cancel request takes effect well under a frame; the cost is one cheap
#: event check per interval.
_CANCEL_POLL_SECONDS = 0.01


class CancellationToken:
    """A thread-safe one-shot cancellation flag shared with a provider call."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation.  Idempotent."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def reset(self) -> None:
        """Clear the flag (mainly for tests)."""
        self._event.clear()

    def raise_if_cancelled(self, provider_id: str = "") -> None:
        if self._event.is_set():
            raise provider_cancelled_error(provider_id)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or *timeout*. Returns ``True`` if cancelled."""
        return self._event.wait(timeout)


def run_with_cancellation(
    fn: Callable[[], Any],
    cancellation: CancellationToken | None = None,
    provider_id: str = "",
) -> Any:
    """Run a blocking *fn* so that a cancel request takes effect promptly.

    A blocking socket read cannot be interrupted cooperatively, so the call runs
    on a daemon worker thread and the caller polls the token.  When the token is
    set the caller raises a normalized ``PROVIDER_CANCELLED`` immediately and
    abandons the worker (its result is discarded); the socket itself is closed by
    the OS when the process exits or the peer times out.  With no token the call
    runs inline, so an un-cancellable caller pays nothing.

    Any exception raised by *fn* is re-raised on the caller thread unchanged, so
    the transport's normalized errors keep their identity.
    """
    if cancellation is None:
        return fn()

    cancellation.raise_if_cancelled(provider_id)

    result: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:
            # Re-raised on the caller thread; the wrapper must not swallow it.
            result["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    while worker.is_alive():
        if cancellation.wait(_CANCEL_POLL_SECONDS):
            raise provider_cancelled_error(provider_id)
    if "error" in result:
        raise result["error"]
    return result.get("value")


__all__ = ["CancellationToken", "run_with_cancellation"]
