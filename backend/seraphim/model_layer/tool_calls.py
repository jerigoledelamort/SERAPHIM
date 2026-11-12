# SERAPHIM MODEL LAYER — streaming tool-call assembly (S14).
#
# An OpenAI-compatible endpoint streams a tool call in fragments: the first chunk
# carries the call id and function name, later chunks carry slices of the JSON
# argument string, correlated by a per-chunk ``index``.  Reassembling that
# correctly is the whole point of this module:
#
#   * fragments are appended per ``index``, never per position in the array
#     (a server may interleave two calls);
#   * a call is returned only when it is complete *and* its argument string
#     parses as a JSON object — a partially received call never becomes a
#     ``ToolCall``, so an unvalidated tool can never run;
#   * duplicate call ids across different indexes are rejected (the correlation
#     to a tool result would be ambiguous);
#   * size limits are enforced while appending, so a runaway endpoint cannot
#     exhaust memory.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seraphim.contracts.sanitization import sanitize_text
from seraphim.model_layer.errors import provider_response_invalid_error
from seraphim.model_layer.response import ToolCall, normalize_tool_calls


@dataclass(frozen=True)
class ToolCallLimits:
    """Caps applied while assembling streamed tool calls."""

    #: Maximum number of distinct calls in one response.
    max_calls: int = 64
    #: Maximum assembled argument payload per call, in bytes.
    max_arguments_bytes: int = 1_000_000
    #: Maximum function-name length per call.
    max_name_bytes: int = 256

    def __post_init__(self) -> None:
        for name in ("max_calls", "max_arguments_bytes", "max_name_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"ToolCallLimits.{name} must be a non-negative int")


@dataclass
class _PartialCall:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""

    @property
    def arguments_bytes(self) -> int:
        return len(self.arguments.encode("utf-8", errors="replace"))


class ToolCallAccumulator:
    """Collects streamed tool-call fragments into validated ``ToolCall`` objects.

    Usage::

        acc = ToolCallAccumulator("openai")
        acc.feed(index=0, call_id="call_1", name="read_file", arguments_delta='{"pa')
        acc.feed(index=0, arguments_delta='th":"a.txt"}')
        calls = acc.finish()          # -> [ToolCall(id="call_1", ...)]

    ``finish`` is the single point where a fragment becomes a callable object: it
    parses and validates every argument payload and rejects the whole set if any
    call is incomplete, malformed, duplicated or oversized.  Callers therefore
    never see a partially valid batch, which is what keeps a broken stream from
    executing half a plan.
    """

    def __init__(self, provider_id: str, *, limits: ToolCallLimits | None = None) -> None:
        self.provider_id = provider_id
        self.limits = limits or ToolCallLimits()
        self._calls: dict[int, _PartialCall] = {}
        #: True when at least one id was synthesized (the endpoint omitted it).
        self.synthesized_ids = False

    # -- Feeding -------------------------------------------------------------

    def feed(
        self,
        *,
        index: int,
        call_id: str = "",
        name: str = "",
        arguments_delta: str = "",
    ) -> None:
        """Append one streamed fragment.

        ``index`` is the provider's correlation key.  A negative index is
        rejected: without it, fragments of two calls could not be told apart.
        """
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise provider_response_invalid_error(
                self.provider_id,
                safe_message=f"streamed tool call has an invalid index {index!r}",
            )

        partial = self._calls.get(index)
        if partial is None:
            if len(self._calls) >= self.limits.max_calls:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed response has more than {self.limits.max_calls} tool calls"
                    ),
                    retryable=False,
                )
            partial = _PartialCall(index=index)
            self._calls[index] = partial

        if call_id:
            candidate = sanitize_text(call_id)
            if partial.id and partial.id != candidate:
                # The same index changed id mid-stream: the endpoint is not
                # speaking the protocol we can correlate against.
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed tool call index {index} changed its id mid-stream"
                    ),
                    retryable=False,
                )
            partial.id = candidate

        if name:
            candidate_name = sanitize_text(name)
            if not partial.name:
                partial.name = candidate_name
            elif candidate_name == partial.name or partial.name.endswith(candidate_name):
                # A repeat of the whole name, or of its tail: nothing to add.
                pass
            elif candidate_name.startswith(partial.name):
                # The endpoint re-sends the name cumulatively and has now sent
                # more of it: keep the longer, authoritative value instead of
                # appending a duplicate ("read" then "read_file" must not become
                # "readread_file").
                partial.name = candidate_name
            else:
                # A genuine continuation split across chunks ("read" + "_file").
                partial.name = sanitize_text(partial.name + candidate_name)
            if len(partial.name.encode("utf-8", errors="replace")) > self.limits.max_name_bytes:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed tool call name exceeds {self.limits.max_name_bytes} bytes"
                    ),
                    retryable=False,
                )

        if arguments_delta:
            if not isinstance(arguments_delta, str):
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message="streamed tool call argument fragment is not a string",
                )
            partial.arguments += arguments_delta
            if partial.arguments_bytes > self.limits.max_arguments_bytes:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed tool call arguments exceed "
                        f"{self.limits.max_arguments_bytes} bytes"
                    ),
                    retryable=False,
                )

    # -- Completion ----------------------------------------------------------

    @property
    def pending_indexes(self) -> list[int]:
        """Indexes seen so far, sorted (for diagnostics and tests)."""
        return sorted(self._calls)

    def has_calls(self) -> bool:
        return bool(self._calls)

    def finish(self) -> list[ToolCall]:
        """Validate every accumulated call and return them in index order.

        Raises a normalized ``RESPONSE_FORMAT_INVALID`` when the set is not
        usable as a whole: a missing name, malformed JSON arguments, a duplicate
        id, or an unfinished payload.  Nothing is returned in that case, so the
        caller cannot accidentally execute a partial batch.
        """
        if not self._calls:
            return []

        flattened: list[dict[str, Any]] = []
        seen_ids: dict[str, int] = {}
        for index in sorted(self._calls):
            partial = self._calls[index]
            call_id = partial.id
            if not call_id:
                # The endpoint omitted the id.  Synthesize a deterministic one so
                # the call can still be answered, and report that we did.
                call_id = f"{self.provider_id}_call_{index}"
                self.synthesized_ids = True
            if not partial.name:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed tool call #{index} has no function name; "
                        f"an unnamed tool cannot be invoked"
                    ),
                    retryable=False,
                )
            if call_id in seen_ids:
                raise provider_response_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"streamed tool calls #{seen_ids[call_id]} and #{index} share the id "
                        f"{call_id!r}; the tool result could not be correlated"
                    ),
                    retryable=False,
                )
            seen_ids[call_id] = index
            flattened.append(
                {
                    "id": call_id,
                    "name": partial.name,
                    # The assembled payload is untrusted server data and is
                    # scrubbed as a whole: a credential split across fragments
                    # cannot be caught per fragment, but it is caught here before
                    # it becomes a contract field.
                    "arguments": sanitize_text(partial.arguments),
                }
            )

        # ``normalize_tool_calls`` performs the JSON parse and the object-shape
        # check; a malformed or truncated payload raises here and no call is
        # returned at all.
        return normalize_tool_calls(flattened, self.provider_id)

    def reset(self) -> None:
        self._calls = {}
        self.synthesized_ids = False


__all__ = ["ToolCallAccumulator", "ToolCallLimits"]
