# S12 tests — deterministic offline FakeProvider and an offline agent loop.
#
# These tests must never touch the network: the fake provider performs no I/O.

import threading
import time

import pytest
from seraphim.model_layer.cancellation import CancellationToken
from seraphim.model_layer.capabilities import ProviderCapabilities
from seraphim.model_layer.content import Message
from seraphim.model_layer.errors import ProviderError, ProviderErrorKind
from seraphim.model_layer.fake import FakeProvider, FakeTurn
from seraphim.model_layer.health import HealthStatus
from seraphim.model_layer.request import ModelRequest, ToolSpec
from seraphim.model_layer.response import FinishReason


def _request(**kwargs) -> ModelRequest:
    return ModelRequest(messages=[Message.user("hello")], **kwargs)


class TestSuccess:
    def test_returns_text(self) -> None:
        provider = FakeProvider.success("answer")
        resp = provider.generate(_request())
        assert resp.text() == "answer"
        assert resp.finish_reason == FinishReason.STOP
        assert resp.provider == "fake"
        assert resp.model == "fake-model"

    def test_usage_reported(self) -> None:
        resp = FakeProvider.success("answer").generate(_request())
        assert resp.usage.total_tokens > 0

    def test_deterministic_ids(self) -> None:
        provider = FakeProvider.success("x")
        first = provider.generate(_request()).id
        second = provider.generate(_request()).id
        assert first == "fake_resp_0"
        assert second == "fake_resp_1"

    def test_reset_restores_counters(self) -> None:
        provider = FakeProvider.success("x")
        provider.generate(_request())
        provider.reset()
        assert provider.generate(_request()).id == "fake_resp_0"

    def test_reset_restores_script(self) -> None:
        provider = FakeProvider(
            script=[FakeTurn(text="only")], default_text="fallback"
        )
        provider.generate(_request())
        provider.reset()
        assert provider.generate(_request()).text() == "only"

    def test_fixed_created_at_gives_reproducible_dump(self) -> None:
        provider = FakeProvider(
            script=[FakeTurn(text="x")], fixed_created_at="2026-01-01T00:00:00.000Z"
        )
        first = provider.generate(_request()).to_dict()
        provider.reset()
        second = provider.generate(_request()).to_dict()
        assert first == second
        assert first["created_at"] == "2026-01-01T00:00:00.000Z"

    def test_no_network_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Any socket use would explode: proves the provider is truly offline.
        import socket

        def _boom(*args, **kwargs):  # pragma: no cover - only runs on failure
            raise AssertionError("FakeProvider must not open sockets")

        monkeypatch.setattr(socket, "socket", _boom)
        monkeypatch.setattr(socket, "create_connection", _boom)
        assert FakeProvider.success("x").generate(_request()).text() == "x"


class TestToolCalls:
    def test_tool_call_response(self) -> None:
        provider = FakeProvider.with_tool_calls(
            [{"name": "filesystem.read_file", "arguments": {"path": "a.txt"}}]
        )
        resp = provider.generate(_request())
        assert resp.finish_reason == FinishReason.TOOL_CALLS
        assert len(resp.tool_calls) == 1
        call = resp.tool_calls[0]
        assert call.name == "filesystem.read_file"
        assert call.arguments == {"path": "a.txt"}
        assert call.id == "call_0"

    def test_multiple_calls_get_distinct_ids(self) -> None:
        provider = FakeProvider.with_tool_calls(
            [{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]
        )
        calls = provider.generate(_request()).tool_calls
        assert [c.id for c in calls] == ["call_0", "call_1"]

    def test_scripted_json_string_arguments_are_parsed(self) -> None:
        provider = FakeProvider.with_tool_calls(
            [{"name": "t", "arguments": '{"a": 1}'}]
        )
        assert provider.generate(_request()).tool_calls[0].arguments == {"a": 1}

    def test_malformed_arguments_do_not_produce_a_call(self) -> None:
        provider = FakeProvider.with_tool_calls([{"name": "t", "arguments": "{oops"}])
        with pytest.raises(ProviderError) as exc:
            provider.generate(_request())
        assert exc.value.code == "RESPONSE_FORMAT_INVALID"


class TestTimeout:
    def test_timeout_without_network(self) -> None:
        # A scripted delay larger than the request timeout must fail fast and
        # deterministically, with no socket and no real waiting.
        provider = FakeProvider.timing_out(delay_seconds=60.0)
        started = time.monotonic()
        with pytest.raises(ProviderError) as exc:
            provider.generate(_request(timeout_seconds=1.0))
        assert exc.value.kind == ProviderErrorKind.TIMEOUT
        assert exc.value.code == "PROVIDER_TIMEOUT"
        assert exc.value.retryable is True
        assert time.monotonic() - started < 1.0

    def test_delay_within_timeout_succeeds(self) -> None:
        provider = FakeProvider(
            script=[FakeTurn(text="late", delay_seconds=0.02)],
            capabilities=ProviderCapabilities(),
        )
        resp = provider.generate(_request(timeout_seconds=5.0))
        assert resp.text() == "late"

    def test_sleep_can_be_disabled_for_fast_tests(self) -> None:
        provider = FakeProvider(
            script=[FakeTurn(text="late", delay_seconds=30.0)],
            sleep=False,
        )
        started = time.monotonic()
        assert provider.generate(_request()).text() == "late"
        assert time.monotonic() - started < 1.0


class TestFailure:
    @pytest.mark.parametrize(
        "kind",
        [
            ProviderErrorKind.UNAVAILABLE,
            ProviderErrorKind.AUTH,
            ProviderErrorKind.RATE_LIMITED,
            ProviderErrorKind.INVALID_REQUEST,
        ],
    )
    def test_normalized_failure(self, kind: str) -> None:
        provider = FakeProvider.failing(kind)
        with pytest.raises(ProviderError) as exc:
            provider.generate(_request())
        assert exc.value.kind == kind

    def test_failure_does_not_leak_secret(self) -> None:
        secret = "sk-" + "Q" * 24
        provider = FakeProvider.failing(ProviderErrorKind.AUTH, message=f"key {secret}")
        with pytest.raises(ProviderError) as exc:
            provider.generate(_request())
        assert secret not in exc.value.safe_message
        assert secret not in str(exc.value)


class TestRefusal:
    def test_refusal_finish_reason(self) -> None:
        resp = FakeProvider.refusing("I cannot do that.").generate(_request())
        assert resp.finish_reason == FinishReason.REFUSAL
        assert "cannot" in resp.text()

    def test_content_filter_reason(self) -> None:
        resp = FakeProvider.refusing(reason=FinishReason.CONTENT_FILTER).generate(_request())
        assert resp.finish_reason == FinishReason.CONTENT_FILTER


class TestCancellation:
    def test_pre_cancelled_token_raises(self) -> None:
        token = CancellationToken()
        token.cancel()
        with pytest.raises(ProviderError) as exc:
            FakeProvider.success("x").generate(_request(), token)
        assert exc.value.kind == ProviderErrorKind.CANCELLED
        assert exc.value.code == "PROVIDER_CANCELLED"

    def test_mid_flight_cancellation_interrupts_delay(self) -> None:
        provider = FakeProvider(
            script=[FakeTurn(text="never", delay_seconds=5.0)],
            capabilities=ProviderCapabilities(),
        )
        token = CancellationToken()
        errors: list[ProviderError] = []

        def run() -> None:
            try:
                provider.generate(_request(), token)
            except ProviderError as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        thread = threading.Thread(target=run)
        started = time.monotonic()
        thread.start()
        time.sleep(0.05)
        token.cancel()
        thread.join(timeout=2.0)
        elapsed = time.monotonic() - started

        assert not thread.is_alive(), "cancellation did not interrupt the call"
        assert elapsed < 2.0
        assert len(errors) == 1
        assert errors[0].kind == ProviderErrorKind.CANCELLED

    def test_cancelled_call_does_not_advance_ids(self) -> None:
        provider = FakeProvider.success("x")
        token = CancellationToken()
        token.cancel()
        with pytest.raises(ProviderError):
            provider.generate(_request(), token)
        # The first successful call still gets response id 0.
        assert provider.generate(_request()).id == "fake_resp_0"

    def test_cancellation_after_completion_is_harmless(self) -> None:
        provider = FakeProvider.success("done")
        token = CancellationToken()
        resp = provider.generate(_request(), token)
        token.cancel()
        assert resp.text() == "done"


class TestHealth:
    def test_default_online(self) -> None:
        health = FakeProvider.success("x").health_check()
        assert health.status == HealthStatus.ONLINE
        assert health.is_available is True

    def test_configured_status(self) -> None:
        health = FakeProvider(health_status=HealthStatus.OFFLINE).health_check()
        assert health.status == HealthStatus.OFFLINE
        assert health.is_available is False

    def test_invalid_status_falls_back_to_unknown(self) -> None:
        health = FakeProvider(health_status="BANANA").health_check()
        assert health.status == HealthStatus.UNKNOWN


class TestStreamingStub:
    def test_stream_emits_start_then_done(self) -> None:
        provider = FakeProvider.success("x")
        events = list(provider.stream(_request(stream=True)))
        assert [e.type for e in events] == ["start", "done"]
        assert events[1].response.text() == "x"

    def test_stream_without_capability_raises(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(streaming=False))
        with pytest.raises(ProviderError) as exc:
            list(provider.stream(_request(stream=True)))
        assert exc.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"

    def test_stream_reports_a_generate_failure_as_a_terminal_error(self) -> None:
        # A failure after START must not escape as an exception: a consumer of the
        # event stream relies on exactly one terminal event, always last (S14
        # review finding M5).
        provider = FakeProvider(
            capabilities=ProviderCapabilities(streaming=True),
            script=[FakeTurn(error_kind=ProviderErrorKind.TIMEOUT, error_message="slow")],
        )
        events = list(provider.stream(_request(stream=True)))
        assert [e.type for e in events] == ["start", "error"]
        assert events[-1].error.kind == ProviderErrorKind.TIMEOUT


class TestScriptedSequence:
    def test_turns_consumed_in_order(self) -> None:
        provider = FakeProvider(
            script=[
                FakeTurn(tool_calls=[{"name": "t", "arguments": {}}]),
                FakeTurn(text="final"),
            ]
        )
        first = provider.generate(_request())
        second = provider.generate(_request())
        assert first.has_tool_calls()
        assert second.text() == "final"

    def test_exhausted_script_uses_default_text(self) -> None:
        provider = FakeProvider(script=[FakeTurn(text="only")], default_text="fallback")
        provider.generate(_request())
        assert provider.generate(_request()).text() == "fallback"


class TestOfflineAgentLoop:
    """Golden scenario §20.2 #1: an agent loop that runs fully offline."""

    def test_tool_call_then_final_answer(self) -> None:
        provider = FakeProvider(
            script=[
                FakeTurn(tool_calls=[{"name": "filesystem.read_file", "arguments": {"path": "a.txt"}}]),
                FakeTurn(text="The file contains: hello"),
            ],
            capabilities=ProviderCapabilities(tool_calls=True),
        )

        # Turn 1: the model asks for a tool call.
        request = ModelRequest(
            messages=[Message.user("read a.txt")],
            tools=[ToolSpec(name="filesystem.read_file", parameters={"type": "object"})],
        )
        response = provider.generate(request)
        assert response.finish_reason == FinishReason.TOOL_CALLS
        call = response.tool_calls[0]

        # The runtime would execute the tool; here we supply a deterministic result.
        request.messages.append(Message.assistant(response.text()))
        request.messages.append(Message.tool_result(call.id, "hello"))

        # Turn 2: the model answers using the tool result.
        final = provider.generate(request)
        assert final.finish_reason == FinishReason.STOP
        assert "hello" in final.text()
        assert provider.last_request is request
