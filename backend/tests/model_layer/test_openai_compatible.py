"""S13: OpenAI-compatible provider against a loopback mock HTTP server.

Every test here talks to an in-process ``http.server`` bound to 127.0.0.1 on an
ephemeral port: no external network, no provider account, no tokens.  The mock
also records the requests it received, so a test can assert on the exact wire
payload and headers — including the fact that a credential *was* sent while no
log, error or dump ever contains it.
"""

from __future__ import annotations

import inspect
import json
import logging
import socket
import threading
import time
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_text
from seraphim.model_layer import (
    CancellationToken,
    ImagePart,
    Message,
    ModelRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderCapabilities,
    ProviderErrorKind,
    TextPart,
    ToolSpec,
    build_openai_compatible_provider,
)
from seraphim.sanctum.secrets import InMemorySecretStore

TEST_KEY = "sk-test-abcdefghijklmnopqrstuvwxyz0123456789"

# ---------------------------------------------------------------------------
# Loopback mock server
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # silence the server's own logging
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
        status, headers, body = self.server.behaviour(record)  # type: ignore[attr-defined]

        if body is None:
            payload = b""
        elif isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json", **headers}
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = body

        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    do_GET = _serve
    do_POST = _serve


class _SilentServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A cancelled/timed-out test abandons its socket; the handler's late write
        # then fails.  That is expected and must not print a traceback.
        return


@contextmanager
def mock_server(behaviour):
    """Start a loopback server running *behaviour*; yields the server object."""
    server = _SilentServer(("127.0.0.1", 0), _Handler)
    server.requests = []  # type: ignore[attr-defined]
    server.behaviour = behaviour  # type: ignore[attr-defined]
    # A short poll interval keeps teardown fast (~50ms instead of ~500ms); the
    # suite starts one server per test.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: Any) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def responds(status: int = 200, body: Any = None, headers: dict[str, str] | None = None):
    """A behaviour that answers immediately."""

    def _behaviour(record: dict[str, Any]) -> tuple[int, dict[str, str], Any]:
        return status, dict(headers or {}), body

    return _behaviour


def sleeps(delay: float, status: int = 200, body: Any = None):
    """A behaviour that answers after *delay* seconds."""

    def _behaviour(record: dict[str, Any]) -> tuple[int, dict[str, str], Any]:
        time.sleep(delay)
        return status, {}, body

    return _behaviour


def closed_port() -> int:
    """A port that is (almost certainly) not listening."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@contextmanager
def dropping_server():
    """A listener that accepts a connection and closes it without a response.

    This is the deterministic "network failure" case: whatever the OS calls a
    refused connect, a dropped connection is unambiguously a transport failure.
    """
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    sock.settimeout(0.2)
    port = int(sock.getsockname()[1])
    stop = threading.Event()

    def _accept_and_drop() -> None:
        while not stop.is_set():
            try:
                connection, _ = sock.accept()
            except OSError:
                continue
            with suppress(OSError):
                connection.close()

    thread = threading.Thread(target=_accept_and_drop, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop.set()
        sock.close()
        thread.join(timeout=2)


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def completion(
    *,
    text: str | None = "hello",
    tool_calls: Any = None,
    finish_reason: Any = "stop",
    usage: Any = None,
    model: str = "test-model",
    response_id: str = "chatcmpl-1",
    message_extra: dict[str, Any] | None = None,
    choice_extra: dict[str, Any] | None = None,
    body_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    if message_extra:
        message.update(message_extra)
    choice: dict[str, Any] = {"index": 0, "message": message, "finish_reason": finish_reason}
    if choice_extra:
        choice.update(choice_extra)
    body: dict[str, Any] = {
        "id": response_id,
        "object": "chat.completion",
        "model": model,
        "choices": [choice],
    }
    if usage is not None:
        body["usage"] = usage
    if body_extra:
        body.update(body_extra)
    return body


def tool_call(call_id: str = "call_1", name: str = "read_file", arguments: Any = '{"path":"a"}') -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def make_provider(base: str, *, secret_ref: str = "", secret: str | None = None, **overrides: Any):
    """Build a provider pointing at *base* with optional overrides."""
    resolver = (lambda ref: secret) if secret is not None else None
    config = OpenAICompatibleConfig(
        endpoint=base, model="test-model", secret_ref=secret_ref, **overrides
    )
    return OpenAICompatibleProvider(config, secret_resolver=resolver)


def simple_request(**kwargs: Any) -> ModelRequest:
    kwargs.setdefault("model", "test-model")
    return ModelRequest(messages=[Message.user("hi")], **kwargs)


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_endpoint_is_required(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(endpoint="", model="m")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "endpoint" in exc.value.safe_message

    def test_model_is_required(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(endpoint="http://127.0.0.1:1", model="")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "model_name" in exc.value.safe_message

    def test_endpoint_must_be_absolute_http_url(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(endpoint="127.0.0.1:11434", model="m")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "http(s)" in exc.value.safe_message

    def test_endpoint_must_not_embed_credentials(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(endpoint="https://user:pass@example.test", model="m")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "credentials" in exc.value.safe_message

    def test_timeout_must_be_positive(self):
        with pytest.raises(SeraphimError):
            OpenAICompatibleConfig(endpoint="http://127.0.0.1:1", model="m", timeout_seconds=0)

    def test_unknown_auth_scheme_rejected(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1", model="m", auth_scheme="magic"
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "auth_scheme" in exc.value.safe_message

    def test_extra_headers_must_be_strings(self):
        with pytest.raises(SeraphimError):
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1", model="m", extra_headers={"X": 1}  # type: ignore[dict-item]
            )

    def test_extra_headers_reject_literal_secret(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1",
                model="m",
                extra_headers={"Authorization": TEST_KEY},
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "secret" in exc.value.safe_message
        assert TEST_KEY not in exc.value.safe_message

    def test_safe_description_contains_no_header_values(self):
        config = OpenAICompatibleConfig(
            endpoint="http://127.0.0.1:1",
            model="m",
            secret_ref="provider.test",
            extra_headers={"X-Org": "acme"},
        )
        described = config.to_dict()
        assert described["extra_header_names"] == ["X-Org"]
        # The header *value* is never part of the description, and neither is a
        # raw header mapping.
        assert "acme" not in json.dumps(described)
        assert "extra_headers" not in described
        assert described["secret_ref"] == "provider.test"

    def test_absolute_chat_path_rejected(self):
        """A path field must not be able to redirect the request to another host."""
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1", model="m", chat_path="http://evil.test/v1/chat"
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "chat_path" in exc.value.safe_message

    def test_absolute_health_path_rejected(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1", model="m", health_path="//evil.test/models"
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "health_path" in exc.value.safe_message

    def test_extra_headers_reject_control_characters(self):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint="http://127.0.0.1:1", model="m", extra_headers={"X": "a\r\nX-Injected: b"}
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "control characters" in exc.value.safe_message


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------


class TestSuccessfulGeneration:
    def test_request_model_mismatch_is_rejected_before_any_network_call(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server))
            with pytest.raises(SeraphimError):
                provider.generate(simple_request(model="other-model"))
        assert server.requests == []

    def test_returns_text(self):
        with mock_server(responds(200, completion(text="done"))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.text() == "done"
        assert response.provider == "openai_compatible"
        assert response.model == "test-model"
        assert response.id == "chatcmpl-1"

    def test_posts_to_configured_chat_path(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), chat_path="/custom/chat")
            provider.generate(simple_request())
        assert server.requests[0]["method"] == "POST"
        assert server.requests[0]["path"] == "/custom/chat"

    def test_request_payload_shape(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), max_tokens=256)
            provider.generate(
                ModelRequest(
                    messages=[Message.system("be brief"), Message.user("hi")],
                    model="test-model",
                    temperature=0.2,
                    top_p=0.9,
                )
            )
        payload = json.loads(server.requests[0]["body"])
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["temperature"] == 0.2
        assert payload["top_p"] == 0.9
        assert payload["max_tokens"] == 256
        assert [m["role"] for m in payload["messages"]] == ["system", "user"]
        assert payload["messages"][1]["content"] == "hi"

    def test_request_max_output_tokens_overrides_config(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), max_tokens=256)
            provider.generate(simple_request(max_output_tokens=7))
        assert json.loads(server.requests[0]["body"])["max_tokens"] == 7

    def test_empty_max_tokens_field_omits_the_budget(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), max_tokens=256, max_tokens_field="")
            provider.generate(simple_request())
        payload = json.loads(server.requests[0]["body"])
        assert "max_tokens" not in payload
        assert "max_completion_tokens" not in payload

    def test_alternate_token_budget_field_name(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server), max_tokens=64, max_tokens_field="max_completion_tokens"
            )
            provider.generate(simple_request())
        payload = json.loads(server.requests[0]["body"])
        assert payload["max_completion_tokens"] == 64
        assert "max_tokens" not in payload

    def test_usage_is_parsed(self):
        with mock_server(
            responds(
                200,
                completion(
                    usage={
                        "prompt_tokens": 11,
                        "completion_tokens": 5,
                        "total_tokens": 16,
                        "prompt_tokens_details": {"cached_tokens": 3},
                    }
                ),
            )
        ) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.usage.prompt_tokens == 11
        assert response.usage.completion_tokens == 5
        assert response.usage.total_tokens == 16
        assert response.usage.cached_tokens == 3

    def test_usage_accepts_anthropic_style_field_names(self):
        """A compatible server may report input/output tokens instead."""
        with mock_server(
            responds(200, completion(usage={"input_tokens": 4, "output_tokens": 6}))
        ) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.usage.prompt_tokens == 4
        assert response.usage.completion_tokens == 6
        assert response.usage.total_tokens == 10

    def test_usage_is_zero_when_absent(self):
        with mock_server(responds(200, completion(usage=None))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.usage.total_tokens == 0

    def test_null_content_with_tool_calls(self):
        with mock_server(
            responds(
                200,
                completion(
                    text=None,
                    tool_calls=[tool_call()],
                    finish_reason="tool_calls",
                ),
            )
        ) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            response = provider.generate(simple_request())
        assert response.text() == ""
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "a"}

    def test_tool_calls_are_normalized(self):
        with mock_server(
            responds(200, completion(text="", tool_calls=[tool_call()], finish_reason="tool_calls"))
        ) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            response = provider.generate(simple_request())
        assert len(response.tool_calls) == 1
        call = response.tool_calls[0]
        assert call.id == "call_1"
        assert call.name == "read_file"
        assert call.arguments == {"path": "a"}
        assert call.raw_arguments == '{"path":"a"}'

    def test_tool_call_without_id_is_synthesized_and_reported(self):
        """A known divergence: some compatible servers omit ``tool_calls[].id``."""
        without_id = {"type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        with mock_server(
            responds(200, completion(text="", tool_calls=[without_id], finish_reason="tool_calls"))
        ) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            response = provider.generate(simple_request())
        assert response.tool_calls[0].id == "openai_compatible_call_0"
        metadata = response.provider_metadata("openai_compatible")
        assert metadata["synthesized_tool_call_ids"] is True

    def test_malformed_tool_call_arguments_rejected(self):
        with mock_server(
            responds(
                200,
                completion(
                    text="",
                    tool_calls=[tool_call(arguments="{not json")],
                    finish_reason="tool_calls",
                ),
            )
        ) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert exc.value.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_content_as_part_list(self):
        with mock_server(
            responds(
                200,
                completion(text=None, message_extra={"content": [{"type": "text", "text": "abc"}]}),
            )
        ) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.text() == "abc"

    def test_finish_reason_length(self):
        with mock_server(responds(200, completion(finish_reason="length"))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.finish_reason == "length"

    def test_finish_reason_content_filter(self):
        with mock_server(responds(200, completion(finish_reason="content_filter"))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.finish_reason == "content_filter"

    def test_unknown_finish_reason_is_flagged_not_hidden(self):
        with mock_server(responds(200, completion(finish_reason="surprise"))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request())
        assert response.finish_reason == "stop"
        metadata = response.provider_metadata("openai_compatible")
        assert metadata["finish_reason_raw"] == "surprise"
        assert metadata["unknown_finish_reason"] is True

    def test_tools_are_encoded(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            provider.generate(
                simple_request(
                    tools=[ToolSpec(name="read_file", description="read", parameters={"type": "object"})]
                )
            )
        payload = json.loads(server.requests[0]["body"])
        assert payload["tools"][0]["type"] == "function"
        assert payload["tools"][0]["function"]["name"] == "read_file"

    def test_structured_output_is_encoded_when_declared(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(structured_output=True)
            )
            provider.generate(simple_request(response_schema={"type": "object"}))
        payload = json.loads(server.requests[0]["body"])
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["schema"] == {"type": "object"}

    def test_image_message_is_encoded_as_parts(self):
        from seraphim.model_layer import ImagePart

        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), capabilities=ProviderCapabilities(vision=True))
            provider.generate(
                ModelRequest(
                    messages=[
                        Message(
                            role="user",
                            content=[ImagePart(mime_type="image/png", data="AAAA")],
                        )
                    ],
                    model="test-model",
                )
            )
        payload = json.loads(server.requests[0]["body"])
        parts = payload["messages"][0]["content"]
        assert parts[0]["type"] == "image_url"
        assert parts[0]["image_url"]["url"] == "data:image/png;base64,AAAA"

    def test_tool_result_message_is_encoded(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            provider.generate(
                ModelRequest(
                    messages=[
                        Message.user("hi"),
                        Message.tool_result("call_1", "file contents"),
                    ],
                    model="test-model",
                )
            )
        payload = json.loads(server.requests[0]["body"])
        assert payload["messages"][1]["role"] == "tool"
        assert payload["messages"][1]["tool_call_id"] == "call_1"
        assert payload["messages"][1]["content"] == "file contents"


# ---------------------------------------------------------------------------
# Headers and credentials
# ---------------------------------------------------------------------------


class TestHeadersAndAuth:
    def test_bearer_credential_header(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=TEST_KEY)
            provider.generate(simple_request())
        assert server.requests[0]["headers"]["authorization"] == f"Bearer {TEST_KEY}"

    def test_api_key_scheme_uses_configured_header(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server),
                secret_ref="provider.azure",
                secret=TEST_KEY,
                auth_scheme="api_key",
                auth_header="api-key",
            )
            provider.generate(simple_request())
        headers = server.requests[0]["headers"]
        assert headers["api-key"] == TEST_KEY
        assert "authorization" not in headers

    def test_auth_scheme_none_sends_no_credential(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server),
                secret_ref="provider.test",
                secret=TEST_KEY,
                auth_scheme="none",
            )
            provider.generate(simple_request())
        assert "authorization" not in server.requests[0]["headers"]

    def test_no_secret_ref_sends_no_credential(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server))
            provider.generate(simple_request())
        assert "authorization" not in server.requests[0]["headers"]

    def test_extra_headers_are_sent(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), extra_headers={"X-Org": "acme"})
            provider.generate(simple_request())
        assert server.requests[0]["headers"]["x-org"] == "acme"
        assert server.requests[0]["headers"]["content-type"] == "application/json"

    def test_credential_is_read_from_the_secret_store_and_registered(self):
        store = InMemorySecretStore()
        store.set("provider.test", TEST_KEY)
        with mock_server(responds(200, completion())) as server:
            provider = build_openai_compatible_provider(
                {
                    "id": "m1",
                    "provider": "openai",
                    "model_name": "test-model",
                    "endpoint": base_url(server),
                    "secret_ref": "provider.test",
                },
                secret_resolver=store.get,
            )
            provider.generate(simple_request())
        assert server.requests[0]["headers"]["authorization"] == f"Bearer {TEST_KEY}"
        # Reading the value registered it process-wide, so no sink can echo it.
        assert sanitize_text(f"key is {TEST_KEY}") == "key is [REDACTED]"

    def test_missing_secret_raises_sanctum_error(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), secret_ref="provider.missing", secret=None)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert exc.value.code == ErrorCode.SECRET_NOT_FOUND
        assert server.requests == []


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def _raise(self, behaviour, **overrides: Any):
        with mock_server(behaviour) as server:
            provider = make_provider(base_url(server), **overrides)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        return exc.value

    def test_400_is_invalid_request(self):
        error = self._raise(responds(400, {"error": {"message": "bad field"}}))
        assert error.code == ErrorCode.PROVIDER_REQUEST_INVALID
        assert error.user_action_required is True
        assert "bad field" in error.safe_message

    def test_404_is_invalid_request(self):
        error = self._raise(responds(404, {"error": {"message": "no such model"}}))
        assert error.code == ErrorCode.PROVIDER_REQUEST_INVALID

    def test_401_is_auth_failure(self):
        error = self._raise(responds(401, {"error": {"message": "invalid key"}}))
        assert error.code == ErrorCode.PROVIDER_AUTH_FAILED
        assert error.user_action_required is True
        assert error.retryable is False

    def test_403_is_auth_failure(self):
        error = self._raise(responds(403, {"error": {"message": "forbidden"}}))
        assert error.code == ErrorCode.PROVIDER_AUTH_FAILED

    def test_408_is_timeout(self):
        error = self._raise(responds(408, {}))
        assert error.code == ErrorCode.PROVIDER_TIMEOUT
        assert error.retryable is True

    def test_429_is_rate_limited(self):
        error = self._raise(responds(429, {"error": {"message": "slow down"}}))
        assert error.code == ErrorCode.PROVIDER_RATE_LIMITED
        assert error.retryable is True

    def test_500_is_unavailable(self):
        error = self._raise(responds(500, "boom"))
        assert error.code == ErrorCode.PROVIDER_UNAVAILABLE
        assert error.retryable is True

    def test_503_is_unavailable(self):
        error = self._raise(responds(503, {"error": {"message": "maintenance"}}))
        assert error.code == ErrorCode.PROVIDER_UNAVAILABLE

    def test_malformed_json_body(self):
        error = self._raise(responds(200, "this is not json"))
        assert error.code == ErrorCode.RESPONSE_FORMAT_INVALID
        assert error.retryable is True

    def test_non_object_json_body(self):
        error = self._raise(responds(200, [1, 2, 3]))
        assert error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_missing_choices(self):
        error = self._raise(responds(200, {"id": "x", "model": "test-model"}))
        assert error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_legacy_text_completion_shape_is_rejected(self):
        body = {"id": "x", "choices": [{"text": "legacy", "finish_reason": "stop"}]}
        error = self._raise(responds(200, body))
        assert error.code == ErrorCode.RESPONSE_FORMAT_INVALID
        assert "message" in error.safe_message

    def test_200_with_error_payload_is_invalid(self):
        error = self._raise(responds(200, {"error": {"message": "quota exceeded"}}))
        assert error.code == ErrorCode.RESPONSE_FORMAT_INVALID

    def test_non_json_error_body_still_maps_by_status(self):
        error = self._raise(responds(502, "<html>bad gateway</html>"))
        assert error.code == ErrorCode.PROVIDER_UNAVAILABLE

    def test_error_kind_is_normalized(self):
        with mock_server(responds(401, {})) as server:
            provider = make_provider(base_url(server))
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert getattr(exc.value, "kind", "") == ProviderErrorKind.AUTH


# ---------------------------------------------------------------------------
# Network failures and cancellation
# ---------------------------------------------------------------------------


class TestNetworkAndCancellation:
    def test_unreachable_endpoint_is_a_retryable_transport_error(self):
        """An unreachable port is a normalized, retryable transport failure.

        Which code the OS reports for a refused connect differs by platform
        (Windows reports a connect timeout here), so both are accepted — what
        matters is that it is normalized and retryable, never a raw OSError.
        """
        provider = make_provider(f"http://127.0.0.1:{closed_port()}", timeout_seconds=2)
        with pytest.raises(SeraphimError) as exc:
            provider.generate(simple_request())
        assert exc.value.code in (ErrorCode.PROVIDER_UNAVAILABLE, ErrorCode.PROVIDER_TIMEOUT)
        assert exc.value.retryable is True

    def test_dropped_connection_is_unavailable(self):
        with dropping_server() as base:
            provider = make_provider(base, timeout_seconds=3)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert exc.value.code == ErrorCode.PROVIDER_UNAVAILABLE
        assert exc.value.retryable is True

    def test_request_timeout(self):
        with mock_server(sleeps(1.5, 200, completion())) as server:
            provider = make_provider(base_url(server), timeout_seconds=0.2)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert exc.value.code == ErrorCode.PROVIDER_TIMEOUT

    def test_request_timeout_override_wins(self):
        with mock_server(sleeps(1.5, 200, completion())) as server:
            provider = make_provider(base_url(server), timeout_seconds=10)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request(timeout_seconds=0.2))
        assert exc.value.code == ErrorCode.PROVIDER_TIMEOUT

    def test_pre_cancelled_token_sends_no_request(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server))
            token = CancellationToken()
            token.cancel()
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request(), token)
        assert exc.value.code == ErrorCode.PROVIDER_CANCELLED
        assert server.requests == []

    def test_mid_flight_cancellation(self):
        with mock_server(sleeps(1.0, 200, completion())) as server:
            provider = make_provider(base_url(server), timeout_seconds=30)
            token = CancellationToken()
            timer = threading.Timer(0.15, token.cancel)
            timer.start()
            started = time.monotonic()
            try:
                with pytest.raises(SeraphimError) as exc:
                    provider.generate(simple_request(), token)
            finally:
                timer.cancel()
            elapsed = time.monotonic() - started
        assert exc.value.code == ErrorCode.PROVIDER_CANCELLED
        # Cancellation must take effect promptly, not after the server responds.
        assert elapsed < 0.8

    def test_token_present_but_not_cancelled_returns_the_value(self):
        """The worker's successful result is delivered unchanged."""
        with mock_server(responds(200, completion(text="with token"))) as server:
            provider = make_provider(base_url(server))
            response = provider.generate(simple_request(), CancellationToken())
        assert response.text() == "with token"

    def test_token_present_and_worker_fails_reraises_unchanged(self):
        """A worker exception keeps its identity through the wrapper."""
        with mock_server(responds(429, {"error": {"message": "slow down"}})) as server:
            provider = make_provider(base_url(server))
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request(), CancellationToken())
        assert exc.value.code == ErrorCode.PROVIDER_RATE_LIMITED
        assert getattr(exc.value, "kind", "") == ProviderErrorKind.RATE_LIMITED
        assert exc.value.retryable is True


# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_auth_error_does_not_reveal_the_key(self):
        echoed = {"error": {"message": f"invalid api key: {TEST_KEY}"}}
        with mock_server(responds(401, echoed)) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=TEST_KEY)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        error = exc.value
        assert TEST_KEY not in error.safe_message
        assert TEST_KEY not in json.dumps(error.to_dict())
        assert TEST_KEY not in json.dumps(error.to_diagnostic_dict())
        # The reference is enough to fix the problem and is safe to show.
        assert error.sanitized_details["secret_ref"] == "provider.test"

    def test_error_body_scrubbed_even_for_an_unknown_key_format(self):
        """The value is registered on read, so exact-match redaction applies too."""
        opaque = "zzz-not-a-known-format-value-0001"
        echoed = {"error": {"message": f"rejected: {opaque}"}}
        with mock_server(responds(401, echoed)) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=opaque)
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert opaque not in exc.value.safe_message
        assert opaque not in json.dumps(exc.value.to_diagnostic_dict())

    def test_no_key_in_logs_on_success(self, caplog):
        caplog.set_level(logging.DEBUG)
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=TEST_KEY)
            provider.generate(simple_request())
        text = "\n".join(record.getMessage() for record in caplog.records)
        assert TEST_KEY not in text
        assert "Authorization" not in text
        # The credential *was* sent — the test is not vacuous.
        assert server.requests[0]["headers"]["authorization"] == f"Bearer {TEST_KEY}"

    def test_no_key_in_logs_on_failure(self, caplog):
        caplog.set_level(logging.DEBUG)
        echoed = {"error": {"message": f"invalid api key: {TEST_KEY}"}}
        with mock_server(responds(401, echoed)) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=TEST_KEY)
            with pytest.raises(SeraphimError):
                provider.generate(simple_request())
        text = "\n".join(record.getMessage() for record in caplog.records)
        assert TEST_KEY not in text
        # The failing path really ran (and really sent the key), so the assertion
        # above is not vacuous.
        assert server.requests[0]["headers"]["authorization"] == f"Bearer {TEST_KEY}"

    def test_echoed_key_in_response_fields_is_scrubbed(self):
        """BLOCKER B1: a server that echoes the key into the envelope is defused.

        The endpoint has just seen the credential in a header, so it could place
        it in ``id``/``model``/``content``/``tool_calls``.  Every one of those is
        untrusted input and must be sanitized before it becomes a contract field.
        """
        body = completion(
            text=f"the key is {TEST_KEY}",
            model=TEST_KEY,
            response_id=TEST_KEY,
            tool_calls=[
                {
                    "id": TEST_KEY,
                    "type": "function",
                    "function": {"name": f"leak_{TEST_KEY}", "arguments": f'{{"p":"{TEST_KEY}"}}'},
                }
            ],
            finish_reason="tool_calls",
            body_extra={"system_fingerprint": TEST_KEY},
        )
        with mock_server(responds(200, body)) as server:
            provider = make_provider(
                base_url(server),
                secret_ref="provider.test",
                secret=TEST_KEY,
                capabilities=ProviderCapabilities(tool_calls=True),
            )
            response = provider.generate(simple_request())
        dump = json.dumps(response.to_dict())
        assert TEST_KEY not in dump
        assert "[REDACTED]" in dump
        assert TEST_KEY not in response.text()
        assert TEST_KEY not in response.model
        assert TEST_KEY not in response.tool_calls[0].id
        assert TEST_KEY not in response.tool_calls[0].name
        assert TEST_KEY not in json.dumps(response.tool_calls[0].arguments)
        assert TEST_KEY not in json.dumps(response.metadata)

    def test_echoed_opaque_key_in_response_fields_is_scrubbed(self):
        """Exact-match redaction covers a key whose format no pattern recognises."""
        opaque = "zzz-not-a-known-format-value-0001"
        body = completion(text=f"leaked: {opaque}", model=opaque, response_id=opaque)
        with mock_server(responds(200, body)) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=opaque)
            response = provider.generate(simple_request())
        assert opaque not in json.dumps(response.to_dict())

    def test_redirect_is_not_followed(self):
        """A 3xx must not resend the credential header to another host."""
        with (
            mock_server(responds(200, completion(text="target"))) as target,
            mock_server(
                responds(302, "", {"Location": f"{base_url(target)}/v1/chat/completions"})
            ) as redirector,
        ):
            provider = make_provider(
                base_url(redirector), secret_ref="provider.test", secret=TEST_KEY
            )
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request())
        assert exc.value.code == ErrorCode.PROVIDER_REQUEST_INVALID
        assert "redirect" in exc.value.safe_message
        # The credential was never forwarded.
        assert target.requests == []

    def test_url_userinfo_is_refused_and_never_echoed(self):
        """A credential embedded in the endpoint URL is rejected, not stored."""
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(
                endpoint=f"http://user:{TEST_KEY}@127.0.0.1:1", model="test-model"
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert TEST_KEY not in exc.value.safe_message
        assert TEST_KEY not in json.dumps(exc.value.to_diagnostic_dict())


# ---------------------------------------------------------------------------
# Capabilities: nothing is assumed
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_default_declaration_is_chat_only(self):
        provider = make_provider("http://127.0.0.1:1")
        caps = provider.get_capabilities()
        assert caps.chat is True
        assert caps.tool_calls is False
        assert caps.vision is False
        assert caps.structured_output is False
        assert caps.streaming is False

    def test_tools_rejected_without_declaration(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(base_url(server))
            with pytest.raises(SeraphimError) as exc:
                provider.generate(simple_request(tools=[ToolSpec(name="t")]))
        assert exc.value.code == ErrorCode.PROVIDER_CAPABILITY_UNSUPPORTED
        assert server.requests == []

    def test_tools_allowed_when_declared(self):
        with mock_server(
            responds(200, completion(text="", tool_calls=[tool_call()], finish_reason="tool_calls"))
        ) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(tool_calls=True)
            )
            response = provider.generate(simple_request(tools=[ToolSpec(name="read_file")]))
        assert response.has_tool_calls()

    def test_streaming_rejected_without_declaration(self):
        provider = make_provider("http://127.0.0.1:1")
        with pytest.raises(SeraphimError) as exc:
            list(provider.stream(simple_request()))
        assert exc.value.code == ErrorCode.PROVIDER_CAPABILITY_UNSUPPORTED

    def test_context_limit_is_enforced(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(context_limit=1)
            )
            with pytest.raises(SeraphimError) as exc:
                provider.generate(ModelRequest(messages=[Message.user("x" * 400)], model="m"))
        assert exc.value.code == ErrorCode.PROVIDER_REQUEST_INVALID
        assert server.requests == []

    def test_verified_capabilities_exclude_unobserved_features(self):
        """A declaration is not proof: the verified view stays honest."""
        caps = ProviderCapabilities(tool_calls=True, vision=True)
        with mock_server(responds(200, completion(text="plain"))) as server:
            provider = make_provider(base_url(server), capabilities=caps)
            assert provider.get_capabilities().tool_calls is True  # declared
            assert provider.verified_capabilities().tool_calls is False  # not observed
            provider.generate(simple_request())
            assert provider.verified_capabilities().chat is True
            assert provider.verified_capabilities().tool_calls is False
            assert provider.verified_capabilities().vision is False

    def test_observed_feature_is_published_as_verified(self):
        caps = ProviderCapabilities(tool_calls=True)
        with mock_server(
            responds(200, completion(text="", tool_calls=[tool_call()], finish_reason="tool_calls"))
        ) as server:
            provider = make_provider(base_url(server), capabilities=caps)
            response = provider.generate(simple_request(tools=[ToolSpec(name="t")]))
        assert response.has_tool_calls()
        assert provider.verified_capabilities().tool_calls is True
        assert "tool_calls" in provider.capability_probe().verified

    def test_capability_probe_reports_reachability(self):
        with mock_server(responds(200, {"data": [{"id": "test-model"}]})) as server:
            provider = make_provider(base_url(server), capabilities=ProviderCapabilities(tool_calls=True))
            probe = provider.capability_probe()
        assert probe.reachable is True
        assert probe.status == 200
        # A health probe only proves reachability.  It never ran a completion, so
        # it verifies nothing (C5 review D3): chat stays a declared gap.
        assert probe.verified == frozenset()
        assert "chat" in probe.declared
        assert "chat" in probe.unverified_declared
        # The declared-but-unobserved feature is reported as a gap, not assumed.
        assert "tool_calls" in probe.unverified_declared

    def test_health_check_does_not_verify_chat(self):
        with mock_server(responds(200, {"data": []})) as server:
            provider = make_provider(base_url(server))
            provider.health_check()
        assert provider.verified_capabilities().chat is False

    def test_verified_capabilities_are_empty_before_any_exchange(self):
        with mock_server(responds(200, completion())) as server:
            provider = make_provider(
                base_url(server),
                capabilities=ProviderCapabilities(
                    chat=True, vision=True, structured_output=True, reasoning_metadata=True
                ),
            )
            caps = provider.verified_capabilities()
        assert caps.chat is False
        assert caps.vision is False
        assert caps.structured_output is False
        assert caps.reasoning_metadata is False

    def test_vision_is_not_verified_by_an_image_request(self):
        """Accepting an image part is not evidence the endpoint read it (D3)."""
        with mock_server(responds(200, completion(text="a photo"))) as server:
            provider = make_provider(base_url(server), capabilities=ProviderCapabilities(vision=True))
            provider.generate(
                ModelRequest(
                    messages=[
                        Message(
                            role="user",
                            content=[
                                TextPart("what is this?"),
                                ImagePart(mime_type="image/png", data="AAAA"),
                            ],
                        )
                    ],
                    model="test-model",
                )
            )
        assert provider.verified_capabilities().vision is False

    def test_structured_output_requires_json_evidence(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        with mock_server(responds(200, completion(text="plain prose"))) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(structured_output=True)
            )
            provider.generate(simple_request(response_schema=schema))
        assert provider.verified_capabilities().structured_output is False

        with mock_server(responds(200, completion(text='{"a": "ok"}'))) as server:
            provider = make_provider(
                base_url(server), capabilities=ProviderCapabilities(structured_output=True)
            )
            provider.generate(simple_request(response_schema=schema))
        assert provider.verified_capabilities().structured_output is True

    def test_capability_probe_never_raises_when_unreachable(self):
        provider = make_provider(f"http://127.0.0.1:{closed_port()}", timeout_seconds=2)
        probe = provider.capability_probe()
        assert probe.reachable is False
        assert probe.detail

    def test_capability_probe_dict_is_json_safe(self):
        with mock_server(responds(200, {"data": []})) as server:
            provider = make_provider(base_url(server), capabilities=ProviderCapabilities(tool_calls=True))
            described = provider.capability_probe().to_dict()
        # Plain strings, so the probe can be serialized without a custom encoder.
        # A probe alone verifies nothing: only a completion exchange does (D3).
        assert described["verified"] == []
        assert described["unverified_declared"] == ["chat", "tool_calls"]
        assert json.loads(json.dumps(described))["declared"] == ["chat", "tool_calls"]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_online_when_reachable(self):
        with mock_server(responds(200, {"data": []})) as server:
            provider = make_provider(base_url(server))
            health = provider.health_check()
        assert health.status == "ONLINE"
        assert health.provider_id == "openai_compatible"
        assert health.latency_ms is not None

    def test_degraded_when_credential_rejected(self):
        with mock_server(responds(401, {"error": {"message": "nope"}})) as server:
            provider = make_provider(base_url(server), secret_ref="provider.test", secret=TEST_KEY)
            health = provider.health_check()
        assert health.status == "DEGRADED"
        assert "credential" in health.detail

    def test_degraded_when_health_path_missing(self):
        with mock_server(responds(404, {})) as server:
            provider = make_provider(base_url(server))
            health = provider.health_check()
        assert health.status == "DEGRADED"
        assert "health_path" in health.detail

    def test_offline_when_unreachable(self):
        provider = make_provider(f"http://127.0.0.1:{closed_port()}", timeout_seconds=2)
        health = provider.health_check()
        assert health.status == "OFFLINE"

    def test_health_uses_the_configured_path(self):
        with mock_server(responds(200, {})) as server:
            provider = make_provider(base_url(server), health_path="/healthz")
            provider.health_check()
        assert server.requests[0]["path"] == "/healthz"


# ---------------------------------------------------------------------------
# Factory: endpoint and features come from configuration
# ---------------------------------------------------------------------------


class TestFactory:
    def test_defaults_applied_for_a_pre_s13_entry(self):
        provider = build_openai_compatible_provider(
            {"id": "m1", "provider": "openai", "model_name": "gpt-4o", "endpoint": "https://a.test"}
        )
        assert provider.provider_id == "openai"
        assert provider.config.chat_path == "/v1/chat/completions"
        assert provider.config.health_path == "/v1/models"
        assert provider.config.timeout_seconds == 30.0
        assert provider.config.auth_scheme == "bearer"
        assert provider.get_capabilities().chat is True
        assert provider.get_capabilities().tool_calls is False

    def test_provider_id_falls_back_when_absent(self):
        provider = build_openai_compatible_provider(
            {"id": "m1", "model_name": "m", "endpoint": "https://a.test"}
        )
        assert provider.provider_id == "openai_compatible"

    def test_entry_transport_fields_are_used(self):
        provider = build_openai_compatible_provider(
            {
                "id": "m1",
                "provider": "local",
                "model_name": "llama3",
                "endpoint": "http://127.0.0.1:11434",
                "secret_ref": "provider.local",
                "timeout_seconds": 3.0,
                "chat_path": "/v1/chat/completions",
                "health_path": "/healthz",
                "auth_scheme": "api_key",
                "auth_header": "api-key",
                "max_tokens": 128,
                "max_tokens_field": "max_completion_tokens",
                "extra_headers": {"X-Org": "acme"},
                "capabilities": {"tool_calls": True, "context_limit": 4096},
            }
        )
        config = provider.config
        assert config.timeout_seconds == 3.0
        assert config.auth_scheme == "api_key"
        assert config.auth_header == "api-key"
        assert config.max_tokens == 128
        assert config.max_tokens_field == "max_completion_tokens"
        assert config.extra_headers == {"X-Org": "acme"}
        assert config.capabilities.tool_calls is True
        assert config.capabilities.context_limit == 4096
        assert config.auth_kind == "api_key"
        assert config.chat_url() == "http://127.0.0.1:11434/v1/chat/completions"

    def test_unknown_capability_name_rejected(self):
        with pytest.raises(SeraphimError) as exc:
            build_openai_compatible_provider(
                {
                    "id": "m1",
                    "provider": "openai",
                    "model_name": "m",
                    "endpoint": "https://a.test",
                    "capabilities": {"telepathy": True},
                }
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "telepathy" in exc.value.safe_message

    def test_non_integer_capability_limit_rejected(self):
        with pytest.raises(SeraphimError) as exc:
            build_openai_compatible_provider(
                {
                    "id": "m1",
                    "provider": "openai",
                    "model_name": "m",
                    "endpoint": "https://a.test",
                    "capabilities": {"context_limit": "big"},
                }
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_accepts_a_model_entry_object(self):
        from seraphim.sanctum.config_schemas import ModelEntry

        entry = ModelEntry(
            id="m1",
            provider="openai",
            model_name="gpt-4o",
            endpoint="https://a.test",
            secret_ref="provider.openai",
        )
        provider = build_openai_compatible_provider(entry)
        assert provider.config.model == "gpt-4o"
        assert provider.config.secret_ref == "provider.openai"

    def test_endpoint_is_not_hard_coded(self):
        """Two entries reach two different servers purely from configuration."""
        with (
            mock_server(responds(200, completion(text="A"))) as first,
            mock_server(responds(200, completion(text="B"))) as second,
        ):
            provider_a = build_openai_compatible_provider(
                {"id": "a", "provider": "p", "model_name": "test-model", "endpoint": base_url(first)}
            )
            provider_b = build_openai_compatible_provider(
                {"id": "b", "provider": "p", "model_name": "test-model", "endpoint": base_url(second)}
            )
            assert provider_a.generate(simple_request()).text() == "A"
            assert provider_b.generate(simple_request()).text() == "B"
        assert len(first.requests) == 1
        assert len(second.requests) == 1

    def test_two_entries_with_different_models_are_independent(self):
        """Selecting a model means selecting a config entry, with no CORE change.

        This is the checkpoint C5 portability proof at the provider level: one
        request payload names model A, the other names model B, and each provider
        refuses a request that names the wrong model instead of silently
        rewriting it (D8).
        """
        with (
            mock_server(responds(200, completion(text="A", model="model-a"))) as first,
            mock_server(responds(200, completion(text="B", model="model-b"))) as second,
        ):
            provider_a = build_openai_compatible_provider(
                {"id": "a", "provider": "p", "model_name": "model-a", "endpoint": base_url(first)}
            )
            provider_b = build_openai_compatible_provider(
                {"id": "b", "provider": "p", "model_name": "model-b", "endpoint": base_url(second)}
            )
            assert provider_a.generate(simple_request(model="model-a")).text() == "A"
            assert provider_b.generate(simple_request(model="model-b")).text() == "B"
            with pytest.raises(SeraphimError) as exc:
                provider_a.generate(simple_request(model="model-b"))
        assert exc.value.code == ErrorCode.PROVIDER_REQUEST_INVALID
        assert len(first.requests) == 1  # the mismatch never reached the endpoint
        assert json.loads(first.requests[0]["body"])["model"] == "model-a"

    def test_empty_request_model_uses_the_configured_model(self):
        """No preference in the request is not a conflict: config wins explicitly."""
        with mock_server(responds(200, completion())) as server:
            provider = build_openai_compatible_provider(
                {"id": "a", "provider": "p", "model_name": "cfg-model", "endpoint": base_url(server)}
            )
            provider.generate(ModelRequest(messages=[Message.user("hi")], model=""))
        assert json.loads(server.requests[0]["body"])["model"] == "cfg-model"

    def test_factory_and_secret_store_end_to_end(self):
        store = InMemorySecretStore()
        store.set("provider.test", TEST_KEY)
        with mock_server(responds(200, completion(text="ok"))) as server:
            provider = build_openai_compatible_provider(
                {
                    "id": "m1",
                    "provider": "openai",
                    "model_name": "test-model",
                    "endpoint": base_url(server),
                    "secret_ref": "provider.test",
                },
                secret_resolver=store.get,
            )
            assert provider.health_check().status == "ONLINE"
            response = provider.generate(simple_request())
        assert response.text() == "ok"
        assert TEST_KEY not in json.dumps(response.to_dict())


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------


def test_adapter_source_does_not_import_a_provider_sdk():
    """The wire format is built here; no vendor client is used or required."""
    import seraphim.model_layer.openai_compatible as module

    source = inspect.getsource(module)
    for vendor in ("openai", "anthropic", "httpx", "requests", "litellm"):
        assert f"import {vendor}" not in source
        assert f"from {vendor}" not in source


def test_no_non_loopback_connection_is_attempted(monkeypatch):
    """The whole suite stays on loopback: nothing external is ever contacted."""
    targets: list[Any] = []
    real_connect = socket.socket.connect

    def spy(self, address):
        targets.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", spy)
    with mock_server(responds(200, completion())) as server:
        provider = make_provider(base_url(server))
        provider.generate(simple_request())
    assert targets, "expected at least one connection attempt"
    assert all(address[0] == "127.0.0.1" for address in targets)
