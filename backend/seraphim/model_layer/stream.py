# SERAPHIM MODEL LAYER — normalized stream events (S12 envelope, S14 semantics).
#
# S12 defined the envelope and a deterministic stub; S14 fills in the semantics:
# text deltas, tool-call argument fragments, a completed (validated) tool call,
# usage, a terminal completion, cancellation and errors.
#
# One event shape is consumed by both CORE and the UI (spec §4.5), so a caller
# never has to know which provider produced it.  The ordering contract is
# enforced, not merely documented — see :class:`StreamSequencer`:
#
#   1. ``sequence`` is a monotonically increasing counter starting at 0;
#   2. ``START`` is the first event and appears exactly once;
#   3. exactly one terminal event (``DONE``/``ERROR``/``CANCELLED``) ends the
#      stream, and no event follows it;
#   4. ``TOOL_CALL`` is emitted only for a fully assembled *and* validated call,
#      never for a fragment.

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.sanitization import (
    max_known_secret_length,
    sanitize_dict,
    sanitize_text,
    split_releasable,
)
from seraphim.model_layer.response import ModelResponse, ToolCall, Usage
from seraphim.model_layer.sse import DEFAULT_MAX_EVENT_BYTES
from seraphim.model_layer.tool_calls import ToolCallLimits


class StreamEventType(StrEnum):
    """The complete set of normalized stream events."""

    START = "start"
    TEXT_DELTA = "text_delta"
    #: A tool call began: ``tool_call_index``/``tool_call_id``/``tool_call_name``.
    TOOL_CALL_START = "tool_call_start"
    #: A fragment of that call's JSON arguments (``arguments_delta``).
    TOOL_CALL_ARGS_DELTA = "tool_call_args_delta"
    #: The call is complete and its arguments parsed and validated.
    TOOL_CALL = "tool_call"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


#: Terminal events.  A stream ends with exactly one of these and nothing after.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset(
    {StreamEventType.DONE, StreamEventType.ERROR, StreamEventType.CANCELLED}
)


@dataclass(frozen=True)
class StreamLimits:
    """Caps enforced while consuming one streamed response.

    A stream is untrusted input that arrives incrementally, so every cap is
    checked *while the bytes arrive* rather than after the fact: a broken or
    hostile endpoint is stopped before it can exhaust memory or wedge the
    caller.  The defaults are generous enough that a well-behaved endpoint never
    hits them.

    Every value must be positive; there is no "0 disables" escape hatch, because
    a silently disabled cap is exactly the failure this type exists to prevent.
    """

    #: Total size of one streamed response body, in bytes.
    max_response_bytes: int = 8_000_000
    #: Size of one accumulated SSE event, in bytes.
    max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES
    #: Assembled JSON arguments of one streamed tool call, in bytes.
    max_arguments_bytes: int = 1_000_000
    #: Number of streamed tool calls in one response.
    max_tool_calls: int = 64
    #: Longest silence between two chunks before the stream is abandoned.
    idle_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        for name in (
            "max_response_bytes",
            "max_event_bytes",
            "max_arguments_bytes",
            "max_tool_calls",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"StreamLimits.{name} must be a positive int, got {value!r}")
        idle = self.idle_timeout_seconds
        if isinstance(idle, bool) or not isinstance(idle, (int, float)) or idle <= 0:
            raise ValueError(
                f"StreamLimits.idle_timeout_seconds must be positive, got {idle!r}"
            )

    def tool_call_limits(self) -> ToolCallLimits:
        """The subset of these caps that applies to tool-call assembly."""
        return ToolCallLimits(
            max_calls=self.max_tool_calls,
            max_arguments_bytes=self.max_arguments_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_response_bytes": self.max_response_bytes,
            "max_event_bytes": self.max_event_bytes,
            "max_arguments_bytes": self.max_arguments_bytes,
            "max_tool_calls": self.max_tool_calls,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }


@dataclass
class StreamEvent:
    """One normalized stream event.

    Only the payload named by ``type`` is meaningful:
    ``text_delta`` for TEXT_DELTA; ``tool_call_index``/``tool_call_id``/
    ``tool_call_name`` for TOOL_CALL_START; ``tool_call_index``/
    ``arguments_delta`` for TOOL_CALL_ARGS_DELTA; ``tool_call`` for TOOL_CALL;
    ``usage`` for USAGE; ``response`` for DONE; ``error`` for ERROR/CANCELLED.
    """

    type: str
    sequence: int = 0
    text_delta: str = ""
    tool_call: ToolCall | None = None
    tool_call_index: int = -1
    tool_call_id: str = ""
    tool_call_name: str = ""
    arguments_delta: str = ""
    usage: Usage | None = None
    response: ModelResponse | None = None
    error: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES

    def to_dict(self) -> dict[str, Any]:
        # Free-text fields taken from a provider are sanitized here as well as at
        # the source: ``to_dict`` is a serialization sink, so a value that reached
        # an event by mistake must not be able to leave through it (TB-7).
        return {
            "type": self.type,
            "sequence": self.sequence,
            "text_delta": sanitize_text(self.text_delta) if self.text_delta else "",
            "tool_call": self.tool_call.to_dict() if self.tool_call is not None else None,
            "tool_call_index": self.tool_call_index,
            "tool_call_id": sanitize_text(self.tool_call_id) if self.tool_call_id else "",
            "tool_call_name": sanitize_text(self.tool_call_name) if self.tool_call_name else "",
            "arguments_delta": sanitize_text(self.arguments_delta) if self.arguments_delta else "",
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "response": self.response.to_dict() if self.response is not None else None,
            # A raw exception message is an untrusted free-text field, so it is
            # sanitized before it reaches a log or the UI (S12 review finding m2).
            "error": self._safe_error(),
            "metadata": sanitize_dict(self.metadata) if self.metadata else {},
        }

    def _safe_error(self) -> Any:
        if self.error is None:
            return None
        if hasattr(self.error, "to_dict"):
            return self.error.to_dict()
        return sanitize_text(str(self.error))


class StreamSequencer:
    """Builds stream events while enforcing the ordering contract.

    An adapter never constructs a ``StreamEvent`` directly: it asks the
    sequencer for the next event.  That makes the contract a property of the
    code path rather than a convention, so a consumer can rely on:

    * ``sequence`` strictly increasing from 0 (no gaps, no repeats);
    * ``START`` first and exactly once;
    * exactly one terminal event, always last.

    A violation is a programming error in the adapter, so it raises
    ``RuntimeError`` (it is not a provider failure and must not be normalized
    into one).
    """

    def __init__(self, provider_id: str = "") -> None:
        self.provider_id = provider_id
        self._sequence = 0
        self._started = False
        self._terminated = False

    # -- State ---------------------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def sequence(self) -> int:
        """The sequence number the next event will receive."""
        return self._sequence

    # -- Event builders ------------------------------------------------------

    def start(self, *, metadata: dict[str, Any] | None = None) -> StreamEvent:
        if self._started:
            raise RuntimeError("stream: START emitted twice")
        self._started = True
        return self._emit(StreamEventType.START, metadata=metadata)

    def text_delta(self, text: str) -> StreamEvent:
        return self._emit(StreamEventType.TEXT_DELTA, text_delta=text)

    def tool_call_start(self, index: int, call_id: str = "", name: str = "") -> StreamEvent:
        return self._emit(
            StreamEventType.TOOL_CALL_START,
            tool_call_index=index,
            tool_call_id=call_id,
            tool_call_name=name,
        )

    def tool_call_args_delta(self, index: int, delta: str) -> StreamEvent:
        return self._emit(
            StreamEventType.TOOL_CALL_ARGS_DELTA,
            tool_call_index=index,
            arguments_delta=delta,
        )

    def tool_call(self, call: ToolCall, index: int = -1) -> StreamEvent:
        return self._emit(
            StreamEventType.TOOL_CALL,
            tool_call=call,
            tool_call_index=index,
            tool_call_id=call.id,
            tool_call_name=call.name,
        )

    def usage(self, usage: Usage) -> StreamEvent:
        return self._emit(StreamEventType.USAGE, usage=usage)

    def done(self, response: ModelResponse) -> StreamEvent:
        return self._emit(StreamEventType.DONE, response=response)

    def error(self, error: Any) -> StreamEvent:
        return self._emit(StreamEventType.ERROR, error=error)

    def cancelled(self, error: Any = None) -> StreamEvent:
        return self._emit(StreamEventType.CANCELLED, error=error)

    # -- Internals -----------------------------------------------------------

    def _emit(self, event_type: str, **payload: Any) -> StreamEvent:
        if self._terminated:
            raise RuntimeError(f"stream: event {event_type!r} emitted after a terminal event")
        if not self._started:
            raise RuntimeError(f"stream: event {event_type!r} emitted before START")
        # The event is built *before* the terminal flag is set, so a failure to
        # construct it cannot leave the sequencer in a "already terminated" state.
        event = StreamEvent(type=event_type, sequence=self._sequence, **payload)
        if event_type in TERMINAL_EVENT_TYPES:
            self._terminated = True
        self._sequence += 1
        return event


class RedactingDeltaBuffer:
    """Emits a streamed text fragment without splitting a known secret.

    A delta is emitted as soon as it is produced, but a credential can arrive
    *across* two fragments: scrubbing each fragment on its own cannot catch the
    value, so the halves would reach the UI.  This buffer therefore releases only
    the part that :func:`split_releasable` proves cannot be one half of a secret,
    and scrubs what it releases; a split secret is only ever emitted once the
    whole value is present and can be redacted as a unit.  :meth:`flush` releases
    the remainder when the stream ends.

    Only values the process *knows* to be secret are covered (the configured
    credential, registered by the secret store).  Pattern-only detection stays
    best-effort, as everywhere else.
    """

    __slots__ = ("_buffer", "_max_hold")

    def __init__(self, max_hold: int | None = None) -> None:
        if max_hold is None:
            # Holding is bounded in practice by roughly twice the longest secret.
            # The cap only matters for a pathological stream that keeps
            # re-creating a secret-shaped tail (repeated, periodic text matching
            # a registered value); without it the buffer could grow without
            # bound.  Even then the released chunk is scrubbed, so it never
            # contains a complete secret.
            max_hold = max(4096, 4 * max_known_secret_length())
        self._max_hold = max(0, max_hold)
        self._buffer = ""

    def feed(self, fragment: str) -> str:
        """Append *fragment*; return the sanitized part that is safe to emit."""
        if not fragment:
            return ""
        self._buffer += fragment
        release, self._buffer = split_releasable(self._buffer)
        if len(self._buffer) > self._max_hold:
            release, self._buffer = release + self._buffer, ""
        return sanitize_text(release)

    def flush(self) -> str:
        """Release and sanitize whatever is still held back."""
        emit, self._buffer = self._buffer, ""
        return sanitize_text(emit)


def validate_stream(events: Iterable[StreamEvent]) -> list[StreamEvent]:
    """Consume *events* and assert the ordering contract; return them.

    A convenience for tests and for a caller that buffers a stream: it raises
    ``RuntimeError`` on the same violations the sequencer prevents, so a stream
    produced by any other implementation can be checked too.
    """
    collected: list[StreamEvent] = []
    started = False
    terminated = False
    for expected_sequence, event in enumerate(events):
        if terminated:
            raise RuntimeError(f"event {event.type!r} after a terminal event")
        if event.sequence != expected_sequence:
            raise RuntimeError(
                f"event {event.type!r} has sequence {event.sequence}, expected {expected_sequence}"
            )
        if event.type == StreamEventType.START:
            if started:
                raise RuntimeError("START emitted twice")
            started = True
        elif not started:
            raise RuntimeError(f"event {event.type!r} before START")
        if event.is_terminal:
            terminated = True
        collected.append(event)
    if not terminated:
        raise RuntimeError("stream ended without a terminal event")
    return collected


__all__ = [
    "TERMINAL_EVENT_TYPES",
    "RedactingDeltaBuffer",
    "StreamEvent",
    "StreamEventType",
    "StreamLimits",
    "StreamSequencer",
    "validate_stream",
]
