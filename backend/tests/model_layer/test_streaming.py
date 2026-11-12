"""S14: streaming and tool-call normalization.

Two layers are exercised here:

* the pure pieces — :class:`SSEParser`, :class:`ToolCallAccumulator`,
  :class:`StreamSequencer`, :class:`StreamLimits` — as plain unit tests;
* the adapter — ``OpenAICompatibleProvider.stream`` — against a loopback mock
  server that writes an SSE body in pieces (with configurable delays and a
  configurable hold) so fragmentation, ordering, early close, idle/overall
  timeout and mid-stream cancellation are all deterministic and offline.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import register_known_secret
from seraphim.model_layer import (
    CancellationToken,
    FinishReason,
    Message,
    ModelRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderCapabilities,
    ProviderErrorKind,
    RedactingDeltaBuffer,
    SSEEventTooLargeError,
    SSEParser,
    StreamEventType,
    StreamLimits,
    StreamSequencer,
    ToolCallAccumulator,
    ToolCallLimits,
    ToolSpec,
    UrllibTransport,
    build_openai_compatible_provider,
    validate_stream,
)
from seraphim.model_layer.http_transport import _UrllibStream
from seraphim.sanctum import ModelEntry

TEST_KEY = "sk-test-abcdefghijklmnopqrstuvwxyz0123456789"


# ---------------------------------------------------------------------------
# Loopback streaming mock server
# ---------------------------------------------------------------------------


@dataclass
class StreamPlan:
    """How the mock server answers one streaming request."""

    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    #: Body pieces, in order.  Each is ``str``/``bytes`` or ``(data, delay)``.
    pieces: list[Any] = field(default_factory=list)
    #: When set, advertised ``Content-Length`` (so the client keeps waiting for
    #: more data even though the server will send nothing else).
    declared_length: int | None = None
    #: How long the handler keeps the connection open *after* the pieces.
    hold_seconds: float = 0.0
    content_type: str = "text/event-stream"


class _StreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # silence the server's logging
        return

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        record = {
            "method": self.command,
            "path": self.path,
            "headers": {name.lower(): value for name, value in self.headers.items()},
            "body": raw,
        }
        self.server.requests.append(record)  # type: ignore[attr-defined]
        plan: StreamPlan = self.server.behaviour(record)  # type: ignore[attr-defined]

        normalized: list[tuple[bytes, float]] = []
        for piece in plan.pieces:
            if isinstance(piece, tuple):
                data, delay = piece
            else:
                data, delay = piece, 0.0
            if isinstance(data, str):
                data = data.encode("utf-8")
            normalized.append((data, float(delay)))
        total = plan.declared_length
        if total is None:
            total = sum(len(data) for data, _ in normalized)

        self.send_response(plan.status)
        self.send_header("Content-Type", plan.content_type)
        for name, value in plan.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(total))
        self.end_headers()
        try:
            for data, delay in normalized:
                if delay:
                    time.sleep(delay)
                if data:
                    self.wfile.write(data)
                    self.wfile.flush()
            if plan.hold_seconds:
                # Hold the connection open without sending the rest of the
                # declared body: the client must apply its own timeout.
                self.server.release.wait(plan.hold_seconds)  # type: ignore[attr-defined]
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The client closed first (timeout/cancel) — expected.
            pass

    do_POST = _serve
    do_GET = _serve


class _SilentStreamServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


@contextmanager
def stream_server(behaviour):
    """Start a loopback server running *behaviour*; yields the server object."""
    server = _SilentStreamServer(("127.0.0.1", 0), _StreamHandler)
    server.requests = []  # type: ignore[attr-defined]
    server.behaviour = behaviour  # type: ignore[attr-defined]
    server.release = threading.Event()  # type: ignore[attr-defined]
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.release.set()  # type: ignore[attr-defined]
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: Any) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def planning(plan: StreamPlan):
    return lambda record: plan


# ---------------------------------------------------------------------------
# SSE / chunk builders
# ---------------------------------------------------------------------------


def sse(data: Any, *, event: str = "") -> str:
    """One SSE frame (blank-line terminated)."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {payload}\n\n"


def delta_chunk(
    *,
    content: Any = None,
    tool_calls: Any = None,
    finish_reason: Any = None,
    usage: Any = None,
    response_id: str = "chatcmpl-1",
    model: str = "test-model",
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    chunk: dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def tc_delta(
    index: int | None,
    *,
    call_id: str | None = None,
    name: str | None = None,
    args: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "function"}
    if index is not None:
        entry["index"] = index
    if call_id is not None:
        entry["id"] = call_id
    if name is not None or args is not None:
        function: dict[str, Any] = {}
        if name is not None:
            function["name"] = name
        if args is not None:
            function["arguments"] = args
        entry["function"] = function
    return entry


def make_provider(base: str, *, secret_ref: str = "", secret: str | None = None, **overrides: Any):
    resolver = (lambda ref: secret) if secret is not None else None
    config = OpenAICompatibleConfig(
        endpoint=base, model="test-model", secret_ref=secret_ref, **overrides
    )
    return OpenAICompatibleProvider(config, secret_resolver=resolver)


def stream_provider(base: str, **overrides: Any) -> OpenAICompatibleProvider:
    overrides.setdefault(
        "capabilities",
        ProviderCapabilities(streaming=True, tool_calls=True, supports_cancellation=True),
    )
    return make_provider(base, **overrides)


def simple_request(**kwargs: Any) -> ModelRequest:
    return ModelRequest(messages=[Message.user("hi")], model="test-model", **kwargs)


def collect(provider: OpenAICompatibleProvider, request: ModelRequest, token=None):
    return list(provider.stream(request, token))


def kinds(events) -> list[str]:
    return [event.type for event in events]


def _response():
    from seraphim.model_layer import ModelResponse

    return ModelResponse(id="r1", model="m", provider="p")


# ---------------------------------------------------------------------------
# StreamLimits
# ---------------------------------------------------------------------------


class TestStreamLimits:
    def test_defaults_are_positive(self):
        limits = StreamLimits()
        assert limits.max_response_bytes > 0
        assert limits.max_event_bytes > 0
        assert limits.max_arguments_bytes > 0
        assert limits.max_tool_calls > 0
        assert limits.idle_timeout_seconds > 0

    @pytest.mark.parametrize(
        "field_name", ["max_response_bytes", "max_event_bytes", "max_tool_calls"]
    )
    def test_non_positive_is_rejected(self, field_name):
        with pytest.raises(ValueError):
            StreamLimits(**{field_name: 0})

    def test_tool_call_limits_projection(self):
        limits = StreamLimits(max_tool_calls=3, max_arguments_bytes=99)
        projected = limits.tool_call_limits()
        assert projected.max_calls == 3
        assert projected.max_arguments_bytes == 99

    def test_to_dict_is_serializable(self):
        assert json.loads(json.dumps(StreamLimits().to_dict()))["max_tool_calls"] == 64


# ---------------------------------------------------------------------------
# SSEParser
# ---------------------------------------------------------------------------


class TestSSEParser:
    def test_dispatches_on_blank_line(self):
        parser = SSEParser()
        assert parser.feed_line('data: {"a":1}\n') is None
        message = parser.feed_line("\n")
        assert message is not None
        assert json.loads(message.data) == {"a": 1}

    def test_multi_line_data_is_joined_with_newline(self):
        parser = SSEParser()
        parser.feed_line("data: one\n")
        parser.feed_line("data: two\n")
        message = parser.feed_line("\n")
        assert message is not None
        assert message.data == "one\ntwo"

    def test_comments_are_ignored(self):
        parser = SSEParser()
        assert parser.feed_line(": keep-alive\n") is None
        assert parser.feed_line("\n") is None

    def test_crlf_is_tolerated(self):
        parser = SSEParser()
        parser.feed_line("data: x\r\n")
        message = parser.feed_line("\r\n")
        assert message is not None
        assert message.data == "x"

    def test_done_sentinel(self):
        parser = SSEParser()
        parser.feed_line("data: [DONE]\n")
        message = parser.feed_line("\n")
        assert message is not None and message.is_done

    def test_close_dispatches_a_trailing_event(self):
        parser = SSEParser()
        parser.feed_line("data: tail\n")
        message = parser.close()
        assert message is not None
        assert message.data == "tail"

    def test_event_too_large_is_rejected(self):
        parser = SSEParser(max_event_bytes=10)
        with pytest.raises(SSEEventTooLargeError):
            parser.feed_line("data: " + "x" * 20 + "\n")

    def test_event_size_is_measured_in_bytes_not_characters(self):
        # A multi-byte character is several bytes: counting characters would let
        # a small-looking event exceed the byte cap (S14 review finding).
        parser = SSEParser(max_event_bytes=10)
        with pytest.raises(SSEEventTooLargeError) as exc:
            parser.feed_line("data: " + "\u00e9" * 6 + "\n")  # 12 bytes, 6 characters
        assert exc.value.size == 12

    def test_event_name_is_captured(self):
        parser = SSEParser()
        parser.feed_line("event: ping\n")
        parser.feed_line("data: {}\n")
        message = parser.feed_line("\n")
        assert message is not None and message.event == "ping"


# ---------------------------------------------------------------------------
# ToolCallAccumulator
# ---------------------------------------------------------------------------


class TestToolCallAccumulator:
    def test_fragments_are_reassembled_by_index(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="read_file", arguments_delta='{"pa')
        accumulator.feed(index=0, arguments_delta='th": "a.txt"}')
        calls = accumulator.finish()
        assert len(calls) == 1
        assert calls[0].id == "c1"
        assert calls[0].arguments == {"path": "a.txt"}

    def test_interleaved_calls_do_not_mix(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="a", arguments_delta='{"x"')
        accumulator.feed(index=1, call_id="c2", name="b", arguments_delta='{"y"')
        accumulator.feed(index=0, arguments_delta=": 1}")
        accumulator.feed(index=1, arguments_delta=": 2}")
        calls = accumulator.finish()
        assert [call.id for call in calls] == ["c1", "c2"]
        assert calls[0].arguments == {"x": 1}
        assert calls[1].arguments == {"y": 2}

    def test_ordering_follows_index_not_arrival(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=2, call_id="c3", name="c", arguments_delta="{}")
        accumulator.feed(index=0, call_id="c1", name="a", arguments_delta="{}")
        accumulator.feed(index=1, call_id="c2", name="b", arguments_delta="{}")
        assert [call.id for call in accumulator.finish()] == ["c1", "c2", "c3"]

    def test_malformed_json_is_rejected(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="a", arguments_delta='{"x": ')
        with pytest.raises(SeraphimError) as exc:
            accumulator.finish()
        assert exc.value.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_truncated_arguments_are_rejected(self):
        """A stream cut off mid-argument never becomes a callable ToolCall."""
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="a", arguments_delta='{"path": "a')
        with pytest.raises(SeraphimError):
            accumulator.finish()

    def test_non_object_arguments_are_rejected(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="a", arguments_delta="[1, 2]")
        with pytest.raises(SeraphimError):
            accumulator.finish()

    def test_missing_name_is_rejected(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", arguments_delta="{}")
        with pytest.raises(SeraphimError):
            accumulator.finish()

    def test_duplicate_id_across_indexes_is_rejected(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="same", name="a", arguments_delta="{}")
        accumulator.feed(index=1, call_id="same", name="b", arguments_delta="{}")
        with pytest.raises(SeraphimError) as exc:
            accumulator.finish()
        assert "correlate" in exc.value.safe_message

    def test_id_change_mid_stream_is_rejected(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=0, call_id="c1", name="a")
        with pytest.raises(SeraphimError):
            accumulator.feed(index=0, call_id="c2")

    def test_missing_id_is_synthesized_deterministically(self):
        accumulator = ToolCallAccumulator("p")
        accumulator.feed(index=3, name="a", arguments_delta="{}")
        calls = accumulator.finish()
        assert calls[0].id == "p_call_3"
        assert accumulator.synthesized_ids is True

    def test_negative_index_is_rejected(self):
        accumulator = ToolCallAccumulator("p")
        with pytest.raises(SeraphimError):
            accumulator.feed(index=-1, name="a", arguments_delta="{}")

    def test_max_calls_limit(self):
        accumulator = ToolCallAccumulator("p", limits=ToolCallLimits(max_calls=1))
        accumulator.feed(index=0, name="a", arguments_delta="{}")
        with pytest.raises(SeraphimError):
            accumulator.feed(index=1, name="b", arguments_delta="{}")

    def test_max_arguments_bytes_limit(self):
        accumulator = ToolCallAccumulator("p", limits=ToolCallLimits(max_arguments_bytes=5))
        with pytest.raises(SeraphimError):
            accumulator.feed(index=0, name="a", arguments_delta='{"path": "long"}')

    def test_max_name_bytes_limit(self):
        accumulator = ToolCallAccumulator("p", limits=ToolCallLimits(max_name_bytes=4))
        with pytest.raises(SeraphimError):
            accumulator.feed(index=0, name="toolong", arguments_delta="{}")

    def test_empty_accumulator_finishes_with_no_calls(self):
        assert ToolCallAccumulator("p").finish() == []
        assert ToolCallAccumulator("p").has_calls() is False

    @pytest.mark.parametrize(
        ("fragments", "expected"),
        [
            (["read", "read_file"], "read_file"),
            (["read_file", "read_file"], "read_file"),
            (["read", "_file"], "read_file"),
            (["re", "ad", "_file"], "read_file"),
        ],
    )
    def test_name_fragments_are_assembled_without_duplication(self, fragments, expected):
        accumulator = ToolCallAccumulator("p")
        for position, fragment in enumerate(fragments):
            # The arguments arrive once, with the last fragment of the name.
            accumulator.feed(
                index=0, name=fragment, arguments_delta="{}" if position == len(fragments) - 1 else ""
            )
        assert accumulator.finish()[0].name == expected


# ---------------------------------------------------------------------------
# StreamSequencer / validate_stream
# ---------------------------------------------------------------------------


class TestStreamSequencer:
    def test_sequence_starts_at_zero_and_increases(self):
        sequencer = StreamSequencer("p")
        events = [
            sequencer.start(),
            sequencer.text_delta("a"),
            sequencer.done(_response()),
        ]
        assert [event.sequence for event in events] == [0, 1, 2]

    def test_start_twice_is_a_programming_error(self):
        sequencer = StreamSequencer("p")
        sequencer.start()
        with pytest.raises(RuntimeError):
            sequencer.start()

    def test_event_before_start_is_rejected(self):
        with pytest.raises(RuntimeError):
            StreamSequencer("p").text_delta("a")

    def test_event_after_terminal_is_rejected(self):
        sequencer = StreamSequencer("p")
        sequencer.start()
        sequencer.done(_response())
        with pytest.raises(RuntimeError):
            sequencer.text_delta("late")

    def test_only_one_terminal_event(self):
        sequencer = StreamSequencer("p")
        sequencer.start()
        sequencer.error(SeraphimError(code=ErrorCode.PROVIDER_UNAVAILABLE, component="c"))
        with pytest.raises(RuntimeError):
            sequencer.done(_response())

    def test_validate_stream_accepts_a_well_formed_stream(self):
        sequencer = StreamSequencer("p")
        events = [sequencer.start(), sequencer.text_delta("a"), sequencer.done(_response())]
        assert validate_stream(events) == events

    def test_validate_stream_rejects_a_gap(self):
        sequencer = StreamSequencer("p")
        events = [sequencer.start(), sequencer.text_delta("a"), sequencer.done(_response())]
        events[1].sequence = 7
        with pytest.raises(RuntimeError):
            validate_stream(events)

    def test_validate_stream_rejects_missing_terminal(self):
        sequencer = StreamSequencer("p")
        with pytest.raises(RuntimeError):
            validate_stream([sequencer.start(), sequencer.text_delta("a")])


# ---------------------------------------------------------------------------
# Adapter: happy paths
# ---------------------------------------------------------------------------


class TestStreamAdapter:
    def test_text_is_streamed_as_deltas(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content="Hel")),
                sse(delta_chunk(content="lo")),
                sse(delta_chunk(content=" world")),
                sse(delta_chunk(finish_reason="stop")),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())

        validate_stream(events)
        deltas = [event.text_delta for event in events if event.type == StreamEventType.TEXT_DELTA]
        assert deltas == ["Hel", "lo", " world"]
        assert kinds(events)[0] == StreamEventType.START
        assert events[-1].type == StreamEventType.DONE
        assert events[-1].response.text() == "Hello world"
        assert events[-1].response.finish_reason == FinishReason.STOP

    def test_request_asks_for_streaming(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="x")), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server))
            collect(provider, simple_request())
            record = server.requests[0]

        body = json.loads(record["body"])
        assert body["stream"] is True
        assert "stream_options" not in body
        assert record["headers"]["accept"] == "text/event-stream"

    def test_stream_include_usage_sends_stream_options(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="x")), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), stream_include_usage=True)
            collect(provider, simple_request())
            body = json.loads(server.requests[0]["body"])
        assert body["stream_options"] == {"include_usage": True}

    def test_usage_is_emitted_only_when_reported(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content="hi")),
                sse(
                    delta_chunk(
                        usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
                    )
                ),
                sse(delta_chunk(finish_reason="stop")),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        usage_events = [event for event in events if event.type == StreamEventType.USAGE]
        assert len(usage_events) == 1
        assert usage_events[0].usage.total_tokens == 7
        assert events[-1].response.usage.completion_tokens == 4

    def test_no_usage_event_without_reported_usage(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="hi")), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert StreamEventType.USAGE not in kinds(events)

    def test_streaming_capability_is_recorded_as_verified(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="hi")), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server))
            collect(provider, simple_request())
        assert provider.verified_capabilities().streaming is True

    def test_streaming_without_declaration_makes_no_request(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="x")), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            provider = make_provider(base_url(server))  # chat only
            with pytest.raises(SeraphimError) as exc:
                list(provider.stream(simple_request()))
            assert server.requests == []
        assert exc.value.code == ErrorCode.PROVIDER_CAPABILITY_UNSUPPORTED

    def test_content_list_delta_is_flattened(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content=[{"type": "text", "text": "ab"}, "cd"])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert events[-1].response.text() == "abcd"


# ---------------------------------------------------------------------------
# Adapter: tool calls
# ---------------------------------------------------------------------------


class TestStreamToolCalls:
    def test_fragmented_arguments_produce_one_validated_call(self):
        plan = StreamPlan(
            pieces=[
                sse(
                    delta_chunk(
                        tool_calls=[
                            tc_delta(0, call_id="call_1", name="read_file", args='{"pa')
                        ]
                    )
                ),
                sse(delta_chunk(tool_calls=[tc_delta(0, args='th": "a.txt"')])),
                sse(delta_chunk(tool_calls=[tc_delta(0, args="}")])),
                sse(delta_chunk(finish_reason="tool_calls")),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)),
                simple_request(tools=[ToolSpec(name="read_file")]),
            )

        validate_stream(events)
        assert kinds(events).count(StreamEventType.TOOL_CALL) == 1
        call_event = next(e for e in events if e.type == StreamEventType.TOOL_CALL)
        assert call_event.tool_call.id == "call_1"
        assert call_event.tool_call.arguments == {"path": "a.txt"}
        # Fragments are surfaced too, but never as a callable call.
        assert kinds(events).count(StreamEventType.TOOL_CALL_ARGS_DELTA) == 3
        assert kinds(events).count(StreamEventType.TOOL_CALL_START) == 1
        assert events[-1].response.finish_reason == FinishReason.TOOL_CALLS

    def test_cumulative_name_fragments_do_not_duplicate(self):
        # Some servers re-send the function name cumulatively ("read" then
        # "read_file"); appending blindly would produce "readread_file" (S14
        # review finding m2).
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="c", name="read")])),
                sse(delta_chunk(tool_calls=[tc_delta(0, name="read_file", args="{}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)),
                simple_request(tools=[ToolSpec(name="read_file")]),
            )
        call = next(e.tool_call for e in events if e.type == StreamEventType.TOOL_CALL)
        assert call.name == "read_file"

    def test_object_arguments_are_serialized_not_silently_dropped(self):
        # A non-conforming server may send the already-parsed arguments object;
        # dropping it would run the tool with empty arguments (S14 review
        # finding m1).
        plan = StreamPlan(
            pieces=[
                sse(
                    delta_chunk(
                        tool_calls=[
                            {
                                "index": 0,
                                "id": "c",
                                "type": "function",
                                "function": {"name": "t", "arguments": {"path": "a.txt"}},
                            }
                        ]
                    )
                ),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)),
                simple_request(tools=[ToolSpec(name="t")]),
            )
        call = next(e.tool_call for e in events if e.type == StreamEventType.TOOL_CALL)
        assert call.arguments == {"path": "a.txt"}

    def test_two_interleaved_calls_are_correlated(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="a", name="t1", args='{"x"')])),
                sse(delta_chunk(tool_calls=[tc_delta(1, call_id="b", name="t2", args='{"y"')])),
                sse(delta_chunk(tool_calls=[tc_delta(0, args=": 1}")])),
                sse(delta_chunk(tool_calls=[tc_delta(1, args=": 2}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)),
                simple_request(tools=[ToolSpec(name="t1")]),
            )
        calls = [e.tool_call for e in events if e.type == StreamEventType.TOOL_CALL]
        assert [(c.id, c.arguments) for c in calls] == [("a", {"x": 1}), ("b", {"y": 2})]

    def test_truncated_arguments_never_emit_a_call(self):
        plan = StreamPlan(
            pieces=[
                sse(
                    delta_chunk(
                        tool_calls=[
                            tc_delta(0, call_id="call_1", name="read_file", args='{"path": "a')
                        ]
                    )
                ),
                # The stream is cut off here: no closing brace, no [DONE].
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)),
                simple_request(tools=[ToolSpec(name="read_file")]),
            )
        validate_stream(events)
        assert StreamEventType.TOOL_CALL not in kinds(events)
        terminal = events[-1]
        assert terminal.type == StreamEventType.ERROR
        assert terminal.error.kind == ProviderErrorKind.RESPONSE_INVALID
        assert events[-1].is_terminal

    def test_malformed_json_arguments_emit_a_terminal_error(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="c", name="t", args="{not json}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)), simple_request(tools=[ToolSpec(name="t")])
            )
        assert StreamEventType.TOOL_CALL not in kinds(events)
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_duplicate_ids_emit_a_terminal_error(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="same", name="a", args="{}")])),
                sse(delta_chunk(tool_calls=[tc_delta(1, call_id="same", name="b", args="{}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)), simple_request(tools=[ToolSpec(name="a")])
            )
        assert StreamEventType.TOOL_CALL not in kinds(events)
        assert events[-1].type == StreamEventType.ERROR

    def test_missing_index_emits_a_terminal_error(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(None, call_id="c", name="t", args="{}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)), simple_request(tools=[ToolSpec(name="t")])
            )
        assert events[-1].type == StreamEventType.ERROR

    def test_missing_id_is_synthesized_and_reported(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, name="t", args="{}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)), simple_request(tools=[ToolSpec(name="t")])
            )
        call_event = next(e for e in events if e.type == StreamEventType.TOOL_CALL)
        assert call_event.tool_call.id == "openai_compatible_call_0"
        assert (
            events[-1].response.provider_metadata()["openai_compatible"][
                "synthesized_tool_call_ids"
            ]
            is True
        )


# ---------------------------------------------------------------------------
# Adapter: early close, timeout, cancellation
# ---------------------------------------------------------------------------


class TestStreamLifecycle:
    def test_early_close_after_a_complete_call_does_not_duplicate_it(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="c1", name="t", args='{"a": 1}')])),
                sse(delta_chunk(finish_reason="tool_calls")),
                # No [DONE]: the server closes the connection instead.
            ]
        )
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server)), simple_request(tools=[ToolSpec(name="t")])
            )
        validate_stream(events)
        assert kinds(events).count(StreamEventType.TOOL_CALL) == 1
        assert events[-1].type == StreamEventType.DONE
        assert len(events[-1].response.tool_calls) == 1

    def test_early_close_with_a_trailing_unterminated_event_is_flushed(self):
        # The final ``data`` line has no blank separator before the connection
        # closes; the parser must still dispatch it.
        plan = StreamPlan(pieces=['data: {"choices":[{"delta":{"content":"tail"}}]}\n'])
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert events[-1].response.text() == "tail"

    def test_close_without_any_event_is_an_error(self):
        plan = StreamPlan(pieces=[])
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_idle_timeout_is_reported(self):
        plan = StreamPlan(
            pieces=[sse(delta_chunk(content="hi"))],
            declared_length=10_000,
            hold_seconds=5.0,
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server),
                timeout_seconds=30.0,
                stream_limits=StreamLimits(idle_timeout_seconds=0.3),
            )
            started = time.monotonic()
            events = collect(provider, simple_request())
            elapsed = time.monotonic() - started
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.kind == ProviderErrorKind.TIMEOUT
        assert "idle" in events[-1].error.safe_message
        assert elapsed < 3.0

    def test_overall_timeout_is_reported(self):
        plan = StreamPlan(
            pieces=[sse(delta_chunk(content="hi"))],
            declared_length=10_000,
            hold_seconds=5.0,
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server),
                timeout_seconds=0.4,
                stream_limits=StreamLimits(idle_timeout_seconds=30.0),
            )
            started = time.monotonic()
            events = collect(provider, simple_request())
            elapsed = time.monotonic() - started
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.kind == ProviderErrorKind.TIMEOUT
        assert elapsed < 3.0

    def test_mid_stream_cancellation_stops_processing(self):
        plan = StreamPlan(
            pieces=[sse(delta_chunk(content="hi"))],
            declared_length=10_000,
            hold_seconds=5.0,
        )
        token = CancellationToken()
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), timeout_seconds=30.0)
            events = []
            for event in provider.stream(simple_request(), token):
                events.append(event)
                if event.type == StreamEventType.TEXT_DELTA:
                    token.cancel()

        assert events[-1].type == StreamEventType.CANCELLED
        assert events[-1].is_terminal
        # Nothing is emitted after the terminal event.
        assert kinds(events).count(StreamEventType.CANCELLED) == 1
        assert StreamEventType.DONE not in kinds(events)

    def test_cancelled_before_start_makes_no_request(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="hi")), "data: [DONE]\n\n"])
        token = CancellationToken()
        token.cancel()
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server))
            with pytest.raises(SeraphimError) as exc:
                list(provider.stream(simple_request(), token))
            assert server.requests == []
        assert exc.value.code == ErrorCode.PROVIDER_CANCELLED

    def test_consumer_that_stops_early_closes_the_connection(self):
        plan = StreamPlan(
            pieces=[sse(delta_chunk(content="hi"))],
            declared_length=10_000,
            hold_seconds=5.0,
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), timeout_seconds=30.0)
            iterator = provider.stream(simple_request())
            first = next(iterator)  # START
            assert first.type == StreamEventType.START
            started = time.monotonic()
            iterator.close()  # must not wait for the held body or the timeout
            elapsed = time.monotonic() - started
        # Closing released the connection instead of blocking on the body the
        # server is still holding (or on the 30s timeout).
        assert elapsed < 1.0, f"closing the stream blocked for {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# Adapter: error mapping and limits
# ---------------------------------------------------------------------------


class TestStreamErrors:
    def test_http_error_status_is_mapped_to_a_terminal_error(self):
        plan = StreamPlan(status=401, pieces=[json.dumps({"error": {"message": "nope"}})])
        with stream_server(planning(plan)) as server:
            events = collect(
                stream_provider(base_url(server), secret_ref="p", secret=TEST_KEY),
                simple_request(),
            )
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == ErrorCode.PROVIDER_AUTH_FAILED

    def test_redirect_is_refused(self):
        plan = StreamPlan(status=302, pieces=[], headers={"Location": "http://evil.test/"})
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == ErrorCode.PROVIDER_REQUEST_INVALID

    def test_broken_json_chunk_is_a_terminal_error(self):
        plan = StreamPlan(pieces=["data: {not json}\n\n", "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            events = collect(stream_provider(base_url(server)), simple_request())
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_response_size_limit(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content="x" * 100)),
                sse(delta_chunk(content="y" * 100)),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server), stream_limits=StreamLimits(max_response_bytes=150)
            )
            events = collect(provider, simple_request())
        assert events[-1].type == StreamEventType.ERROR
        assert "exceeds" in events[-1].error.safe_message

    def test_event_size_limit(self):
        plan = StreamPlan(pieces=[sse(delta_chunk(content="x" * 200)), "data: [DONE]\n\n"])
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server), stream_limits=StreamLimits(max_event_bytes=50)
            )
            events = collect(provider, simple_request())
        assert events[-1].type == StreamEventType.ERROR
        assert events[-1].error.code == "RESPONSE_FORMAT_INVALID"
        assert StreamEventType.TEXT_DELTA not in kinds(events)
        assert StreamEventType.DONE not in kinds(events)

    def test_arguments_size_limit(self):
        plan = StreamPlan(
            pieces=[
                sse(
                    delta_chunk(
                        tool_calls=[
                            tc_delta(0, call_id="c", name="t", args='{"a": "' + "x" * 200 + '"}')
                        ]
                    )
                ),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server), stream_limits=StreamLimits(max_arguments_bytes=50)
            )
            events = collect(provider, simple_request(tools=[ToolSpec(name="t")]))
        assert events[-1].type == StreamEventType.ERROR
        assert StreamEventType.TOOL_CALL not in kinds(events)

    def test_tool_call_count_limit(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(tool_calls=[tc_delta(0, call_id="a", name="t", args="{}")])),
                sse(delta_chunk(tool_calls=[tc_delta(1, call_id="b", name="t", args="{}")])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(
                base_url(server), stream_limits=StreamLimits(max_tool_calls=1)
            )
            events = collect(provider, simple_request(tools=[ToolSpec(name="t")]))
        assert events[-1].type == StreamEventType.ERROR
        assert StreamEventType.TOOL_CALL not in kinds(events)


# ---------------------------------------------------------------------------
# Transport: the streaming read seam
# ---------------------------------------------------------------------------


class _ScriptedResponse:
    """Minimal stand-in for a urllib streaming response.

    Provides only what ``_UrllibStream`` touches: ``status``, ``headers``,
    ``readline(limit)`` and ``close()``.
    """

    def __init__(self, lines: list[bytes], *, status: int = 200) -> None:
        self.status = status
        self.headers = {"Content-Type": "text/event-stream"}
        self._lines = list(lines)
        self.reads = 0
        self.closed = False

    def readline(self, limit: int = -1) -> bytes:
        if self.reads >= len(self._lines):
            return b""
        line = self._lines[self.reads]
        self.reads += 1
        return line

    def close(self) -> None:
        self.closed = True


class TestStreamTransportSeam:
    def test_end_of_stream_is_sticky(self):
        # The protocol says ``read_line`` returns None at the end of the stream;
        # a second call must report the end again instead of an idle stream
        # (S14 review finding m4).
        plan = StreamPlan(pieces=["one\ntwo\n"])
        with stream_server(planning(plan)) as server:
            stream = UrllibTransport(provider_id="t").open_stream(
                "GET", f"{base_url(server)}/s", headers={}, body=None, timeout=5.0
            )
            try:
                assert stream.read_line(timeout=2.0) == "one\n"
                assert stream.read_line(timeout=2.0) == "two\n"
                assert stream.read_line(timeout=2.0) is None
                assert stream.read_line(timeout=0.1) is None
            finally:
                stream.close()

    def test_reader_does_not_buffer_far_ahead_of_the_consumer(self):
        # The background reader is bounded by a byte budget, so a fast endpoint
        # cannot be pulled into memory ahead of the consumer (finding M3).
        response = _ScriptedResponse([b"0123456789\n"] * 200)
        stream = _UrllibStream(response, max_buffered_bytes=32, max_line_bytes=1024)
        try:
            time.sleep(0.3)  # let the reader run as far as it is allowed to
            # 32 bytes of budget with 11-byte lines: three lines are buffered and
            # the fourth read blocks, so an unbounded reader (200 reads) is out.
            assert response.reads <= 5
        finally:
            stream.close()


# ---------------------------------------------------------------------------
# Secrets never leak through a stream
# ---------------------------------------------------------------------------


class TestRedactingDeltaBuffer:
    #: A credential that matches no value pattern, so only exact-value
    #: redaction can catch it: the pattern-free case the hold-back exists for.
    SECRET = "QwErTyUiOp1234567890AbCd"
    #: A secret whose first character also ends it (a border).  Its own tail is
    #: a proper prefix of itself, so a naive cut lands inside the occurrence and
    #: releases almost the whole value.
    BORDERED = "AbcdefghijklmnopqrA"
    #: A periodic secret: every suffix of it is also a prefix.
    PERIODIC = "abcabcabc"

    @staticmethod
    def _leaks(output: str, secret: str) -> bool:
        """True when *output* contains any 8+ character slice of *secret*."""
        window = min(8, len(secret))
        return any(secret[i : i + window] in output for i in range(len(secret) - window + 1))

    def test_plain_text_is_released_immediately(self):
        register_known_secret(self.SECRET)
        buffer = RedactingDeltaBuffer()
        assert buffer.feed("hello") == "hello"
        assert buffer.flush() == ""

    @pytest.mark.parametrize("secret", [SECRET, BORDERED, PERIODIC])
    @pytest.mark.parametrize("split", range(1, len(SECRET)))
    def test_secret_split_at_any_boundary_never_leaks(self, secret, split):
        register_known_secret(secret)
        buffer = RedactingDeltaBuffer()
        emitted = (
            buffer.feed(secret[:split]) + buffer.feed(secret[split:]) + buffer.flush()
        )
        assert emitted == "[REDACTED]"
        assert not self._leaks(emitted, secret)

    @pytest.mark.parametrize("secret", [SECRET, BORDERED, PERIODIC])
    def test_a_complete_secret_in_one_fragment_is_redacted_as_a_unit(self, secret):
        # The border/periodicity case: releasing any prefix here would leave the
        # rest of the value in the tail, and the two halves would reconstruct it.
        register_known_secret(secret)
        buffer = RedactingDeltaBuffer()
        emitted = buffer.feed(secret) + buffer.flush()
        assert emitted == "[REDACTED]"
        assert not self._leaks(emitted, secret)

    @pytest.mark.parametrize("secret", [SECRET, BORDERED, PERIODIC])
    def test_a_character_at_a_time_never_reconstructs_the_secret(self, secret):
        register_known_secret(secret)
        buffer = RedactingDeltaBuffer()
        emitted = "".join(buffer.feed(character) for character in secret) + buffer.flush()
        assert emitted == "[REDACTED]"
        assert not self._leaks(emitted, secret)

    def test_overlapping_distinct_secrets_do_not_reconstruct_each_other(self):
        # Two registered values that share a substring: a cut chosen for one must
        # not split the other.
        register_known_secret(["ZzYyXxWwVvUuTtSs", "VvUuTtSsRrQqPpOo"])
        buffer = RedactingDeltaBuffer()
        emitted = buffer.feed("ZzYyXxWwVvUuTtSsRrQqPpOo") + buffer.flush()
        assert "ZzYyXxWwVvUuTtSs" not in emitted
        assert "VvUuTtSsRrQqPpOo" not in emitted

    def test_surrounding_text_is_preserved_around_a_split_secret(self):
        register_known_secret(self.SECRET)
        buffer = RedactingDeltaBuffer()
        emitted = "".join(
            [
                buffer.feed("start "),
                buffer.feed(self.SECRET[:7]),
                buffer.feed(self.SECRET[7:20]),
                buffer.feed(self.SECRET[20:]),
                buffer.feed(" end"),
                buffer.flush(),
            ]
        )
        assert emitted == "start [REDACTED] end"
        assert not self._leaks(emitted, self.SECRET)

    def test_a_complete_secret_is_redacted_without_being_split(self):
        register_known_secret(self.SECRET)
        buffer = RedactingDeltaBuffer()
        emitted = buffer.feed(f"key: {self.SECRET}!") + buffer.flush()
        assert self.SECRET not in emitted
        assert not self._leaks(emitted, self.SECRET)

    def test_text_is_not_held_when_no_secret_is_known(self):
        buffer = RedactingDeltaBuffer()
        assert buffer.feed(self.SECRET) == self.SECRET

    def test_hold_is_bounded_even_for_a_periodic_stream(self):
        # A pathological stream that keeps re-creating a secret-shaped tail must
        # not grow the buffer without bound; what is released is still scrubbed.
        register_known_secret(self.PERIODIC)
        buffer = RedactingDeltaBuffer(max_hold=64)
        emitted = "".join(buffer.feed(self.PERIODIC) for _ in range(50)) + buffer.flush()
        assert len(buffer._buffer) <= 64
        assert not self._leaks(emitted, self.PERIODIC)


class TestStreamSecretSafety:
    def test_key_is_sent_but_never_appears_in_events(self):
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content=f"the key is {TEST_KEY}")),
                sse(
                    delta_chunk(
                        tool_calls=[
                            tc_delta(0, call_id="c", name="t", args=f'{{"k": "{TEST_KEY}"}}')
                        ]
                    )
                ),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), secret_ref="p", secret=TEST_KEY)
            events = collect(provider, simple_request(tools=[ToolSpec(name="t")]))
            record = server.requests[0]

        # The credential was really sent ...
        assert record["headers"]["authorization"] == f"Bearer {TEST_KEY}"
        # ... yet no serialized event contains it.
        dump = json.dumps([event.to_dict() for event in events], default=str)
        assert TEST_KEY not in dump
        assert events[-1].response.text() == "the key is [REDACTED]"

    def test_error_detail_does_not_leak_the_key(self):
        plan = StreamPlan(status=400, pieces=[json.dumps({"error": {"message": TEST_KEY}})])
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), secret_ref="p", secret=TEST_KEY)
            events = collect(provider, simple_request())
        assert TEST_KEY not in json.dumps(events[-1].to_dict(), default=str)

    def test_secret_split_across_chunks_is_never_emitted_in_halves(self):
        # A pattern-free credential (only exact-value redaction can catch it)
        # arrives in two content deltas: scrubbing each delta on its own would
        # leak the two halves to the UI.
        secret = "QwErTyUiOp1234567890AbCd"
        half = len(secret) // 2
        plan = StreamPlan(
            pieces=[
                sse(delta_chunk(content=f"token is {secret[:half]}")),
                sse(delta_chunk(content=secret[half:])),
                "data: [DONE]\n\n",
            ]
        )
        with stream_server(planning(plan)) as server:
            provider = stream_provider(base_url(server), secret_ref="p", secret=secret)
            events = collect(provider, simple_request())

        deltas = "".join(
            event.text_delta for event in events if event.type == StreamEventType.TEXT_DELTA
        )
        assert "[REDACTED]" in deltas
        # No half of the credential survived anywhere, live or in the response.
        dump = json.dumps([event.to_dict() for event in events], default=str)
        assert secret not in dump
        assert not TestRedactingDeltaBuffer._leaks(dump, secret)
        assert events[-1].response.text() == "token is [REDACTED]"


# ---------------------------------------------------------------------------
# Factory: streaming configuration from a providers.models[] entry
# ---------------------------------------------------------------------------


class TestStreamConfigFromEntry:
    def test_stream_limits_load_from_entry(self):
        provider = build_openai_compatible_provider(
            {
                "endpoint": "http://127.0.0.1:1",
                "model_name": "m",
                "stream_max_response_bytes": 1234,
                "stream_max_event_bytes": 567,
                "stream_max_arguments_bytes": 890,
                "stream_max_tool_calls": 3,
                "stream_idle_timeout_seconds": 2.5,
                "stream_include_usage": True,
            }
        )
        limits = provider.config.stream_limits
        assert limits.max_response_bytes == 1234
        assert limits.max_event_bytes == 567
        assert limits.max_arguments_bytes == 890
        assert limits.max_tool_calls == 3
        assert limits.idle_timeout_seconds == 2.5
        assert provider.config.stream_include_usage is True

    def test_defaults_apply_when_entry_omits_streaming_fields(self):
        provider = build_openai_compatible_provider(
            {"endpoint": "http://127.0.0.1:1", "model_name": "m"}
        )
        assert provider.config.stream_limits == StreamLimits()
        assert provider.config.stream_include_usage is False

    def test_config_defaults_agree_with_the_adapter_limits(self):
        # ``ModelEntry`` (sanctum) cannot import ``model_layer`` — the dependency
        # goes the other way — so the streaming defaults exist twice; this keeps
        # the two copies in sync (S14 review finding m7).
        entry = ModelEntry(id="m", provider="openai", model_name="m")
        limits = StreamLimits()
        assert entry.stream_max_response_bytes == limits.max_response_bytes
        assert entry.stream_max_event_bytes == limits.max_event_bytes
        assert entry.stream_max_arguments_bytes == limits.max_arguments_bytes
        assert entry.stream_max_tool_calls == limits.max_tool_calls
        assert entry.stream_idle_timeout_seconds == limits.idle_timeout_seconds
        tool_limits = ToolCallLimits()
        assert entry.stream_max_arguments_bytes == tool_limits.max_arguments_bytes
        assert entry.stream_max_tool_calls == tool_limits.max_calls

    def test_non_positive_stream_limit_is_rejected(self):
        with pytest.raises(SeraphimError) as exc:
            build_openai_compatible_provider(
                {
                    "endpoint": "http://127.0.0.1:1",
                    "model_name": "m",
                    "stream_max_tool_calls": 0,
                }
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_config_description_includes_stream_limits(self):
        provider = build_openai_compatible_provider(
            {"endpoint": "http://127.0.0.1:1", "model_name": "m"}
        )
        described = provider.config.to_dict()
        assert described["stream_limits"]["max_tool_calls"] == 64
