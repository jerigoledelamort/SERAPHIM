# SERAPHIM MODEL LAYER — incremental Server-Sent Events parser (S14).
#
# A streaming endpoint answers with ``text/event-stream``: a sequence of events
# separated by a blank line, each carrying ``field: value`` lines.  The parser is
# *incremental* on purpose — the transport hands it one line at a time, so a
# caller can react (emit a delta, check cancellation, enforce a deadline) between
# chunks instead of buffering the whole response.
#
# Only the fields SERAPHIM needs are interpreted; unknown fields are ignored per
# the SSE specification.  The parser never assumes a specific provider payload:
# it returns the raw ``data`` string and lets the adapter parse JSON, so a
# malformed payload is reported as a normalized provider error rather than
# crashing here.

from __future__ import annotations

from dataclasses import dataclass

#: Sentinel an OpenAI-compatible endpoint sends as the last ``data`` payload.
STREAM_DONE_SENTINEL = "[DONE]"

#: Default cap on one accumulated event.  A single SSE event is normally tiny
#: (one token or one argument fragment); a much larger value means the endpoint
#: is not speaking the expected protocol, so the parser fails instead of
#: buffering without bound.
DEFAULT_MAX_EVENT_BYTES = 1_000_000


@dataclass(frozen=True)
class SSEMessage:
    """One dispatched SSE event."""

    data: str = ""
    event: str = ""
    id: str = ""

    @property
    def is_done(self) -> bool:
        """True for the OpenAI-compatible end-of-stream sentinel."""
        return self.data.strip() == STREAM_DONE_SENTINEL


class SSEEventTooLargeError(Exception):
    """An accumulated event exceeded ``max_event_bytes``.

    Raised by the parser (a protocol-level problem, not a provider failure); the
    adapter translates it into a normalized ``RESPONSE_FORMAT_INVALID`` error.
    """

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"SSE event of {size} bytes exceeds the {limit}-byte limit")
        self.size = size
        self.limit = limit


class SSEParser:
    """Incremental ``text/event-stream`` parser.

    Feed one line at a time with :meth:`feed_line`; a blank line dispatches the
    buffered event and returns it, otherwise ``None`` is returned.  Line endings
    (``\\n``/``\\r\\n``/``\\r``) are tolerated.

    Args:
        max_event_bytes: Cap on the accumulated ``data`` payload of one event.
            ``0`` disables the cap.
    """

    def __init__(self, *, max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES) -> None:
        self.max_event_bytes = max_event_bytes
        self._data_lines: list[str] = []
        self._event = ""
        self._id = ""
        self._size = 0

    def feed_line(self, line: str) -> SSEMessage | None:
        """Consume one line; return a dispatched message or ``None``."""
        text = line.rstrip("\r\n")

        if text == "":
            return self._dispatch()

        if text.startswith(":"):
            # A comment (often a keep-alive).  Ignored by the specification.
            return None

        field, separator, value = text.partition(":")
        if separator and value.startswith(" "):
            # A single leading space after the colon is part of the framing.
            value = value[1:]

        if field == "data":
            # Counted as encoded bytes, matching the documented limit: a
            # multi-byte character must not count as one byte.
            self._size += len(value.encode("utf-8", errors="replace"))
            if self.max_event_bytes and self._size > self.max_event_bytes:
                raise SSEEventTooLargeError(self._size, self.max_event_bytes)
            self._data_lines.append(value)
        elif field == "event":
            self._event = value
        elif field == "id":
            self._id = value
        # Any other field is ignored (SSE specification).
        return None

    def close(self) -> SSEMessage | None:
        """Dispatch a trailing event that was not terminated by a blank line.

        A stream may be cut off after a complete ``data`` line but before the
        blank separator; discarding that data would silently lose the last
        chunk, so it is dispatched instead.
        """
        return self._dispatch()

    # -- Internals -----------------------------------------------------------

    def _dispatch(self) -> SSEMessage | None:
        if not self._data_lines and not self._event:
            self._reset()
            return None
        message = SSEMessage(
            data="\n".join(self._data_lines),
            event=self._event,
            id=self._id,
        )
        self._reset()
        return message

    def _reset(self) -> None:
        self._data_lines = []
        self._event = ""
        self._id = ""
        self._size = 0


__all__ = [
    "DEFAULT_MAX_EVENT_BYTES",
    "STREAM_DONE_SENTINEL",
    "SSEEventTooLargeError",
    "SSEMessage",
    "SSEParser",
]
