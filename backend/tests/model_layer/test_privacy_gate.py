# SERAPHIM MODEL LAYER — privacy gate integration tests (C5 review D2, D9).
#
# The review found that the SANCTUM privacy policy existed but was never consulted
# by the model layer: an adapter sent context outward under a policy that denies
# external transmission (TB-9, CONTRACTS.md §6.4, spec §4.5).  These tests pin the
# gate in place:
#
# * an external endpoint is denied by the default (deny-by-default) policy, and the
#   denial happens before the credential is read and before the transport is used;
# * a loopback endpoint is a *local* transfer, so a closed policy still lets a
#   local model and the offline test suite run;
# * the provider allow-list is honoured for external endpoints;
# * health/capability probes keep their "never raises" contract and report the
#   denial as OFFLINE/unreachable instead of contacting the endpoint;
# * FakeProvider runs the same gate as a local transfer (it performs no I/O);
# * ``oauth``/``local`` auth schemes are rejected rather than silently sending no
#   credential (D9).

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer import (
    FakeProvider,
    HealthStatus,
    Message,
    ModelRequest,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    PrivacyPolicy,
    ProviderCapabilities,
    build_openai_compatible_provider,
)
from seraphim.model_layer.http_transport import HttpResponse
from seraphim.model_layer.transmission import categories_for_request, endpoint_is_local
from seraphim.sanctum.privacy import (
    REASON_ALLOWED,
    REASON_EXTERNAL_DISABLED,
    REASON_LOCAL_PROVIDER,
    REASON_PROVIDER_NOT_ALLOWED,
)

#: A host that is not loopback, so the policy treats the transfer as external.
#: These tests inject a transport seam, so the address is never contacted.
EXTERNAL = "https://api.example.test"

COMPLETION = {
    "id": "r",
    "object": "chat.completion",
    "model": "m",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ],
}


class RecordingTransport:
    """A transport seam that records calls and never opens a socket."""

    def __init__(self, body: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._body = body if body is not None else COMPLETION

    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: Any, timeout: float
    ) -> HttpResponse:
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        return HttpResponse(
            200, {"Content-Type": "application/json"}, json.dumps(self._body).encode("utf-8")
        )

    def open_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("this test must not open a stream")


class ExplodingTransport:
    """Any use is a failure: proves a denied request never reaches the network."""

    def request(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a denied request must not reach the transport")

    def open_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a denied request must not reach the transport")


def make_request(text: str = "hi") -> ModelRequest:
    return ModelRequest(messages=[Message.user(text)], model="m")


def open_policy(**overrides: Any) -> PrivacyPolicy:
    fields: dict[str, Any] = {
        "allow_external_transmission": True,
        "allowed_providers": frozenset({"openai_compatible"}),
        "require_confirmation": True,
    }
    fields.update(overrides)
    return PrivacyPolicy(**fields)


# ---------------------------------------------------------------------------
# D2: the gate decides before anything can leave the process
# ---------------------------------------------------------------------------


class TestOpenAIAdapterGate:
    def test_external_endpoint_is_denied_without_a_policy(self):
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
        )
        with pytest.raises(SeraphimError) as exc:
            provider.generate(make_request())
        assert exc.value.code == ErrorCode.PRIVACY_TRANSMISSION_DENIED
        assert exc.value.sanitized_details["reason"] == REASON_EXTERNAL_DISABLED
        assert provider.last_privacy_decision is not None
        assert provider.last_privacy_decision.allowed is False

    def test_denied_generate_reads_no_secret(self):
        """Order: policy first, then the credential, then the transport."""
        resolved: list[str] = []
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m", secret_ref="provider.test"),
            secret_resolver=lambda ref: resolved.append(ref) or "SECRET",
            transport=ExplodingTransport(),
        )
        with pytest.raises(SeraphimError):
            provider.generate(make_request())
        assert resolved == []

    def test_allowed_external_send_carries_the_credential(self):
        """Positive control: with an open policy the same config does transmit."""
        transport = RecordingTransport()
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m", secret_ref="provider.test"),
            secret_resolver=lambda ref: "sk-secret-value-1234567890abcdef",
            transport=transport,
            privacy_policy=open_policy(),
        )
        response = provider.generate(make_request())
        assert response.text() == "ok"
        assert len(transport.calls) == 1
        assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-secret-value-1234567890abcdef"
        assert provider.last_privacy_decision.reason == REASON_ALLOWED

    def test_denial_reports_which_context_would_have_left(self):
        """Spec §4.5: the user sees the scope of what was about to be sent."""
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
        )
        with pytest.raises(SeraphimError) as exc:
            provider.generate(make_request())
        details = exc.value.sanitized_details
        assert details["provider"] == "openai_compatible"
        assert "conversation" in details["categories"]

    def test_stream_is_denied_before_any_event(self):
        """A denial is raised in the pre-flight: no ``START`` event is emitted."""
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(
                endpoint=EXTERNAL, model="m", capabilities=ProviderCapabilities(streaming=True)
            ),
            transport=ExplodingTransport(),
        )
        with pytest.raises(SeraphimError) as exc:
            provider.stream(make_request())
        assert exc.value.code == ErrorCode.PRIVACY_TRANSMISSION_DENIED

    def test_health_probe_is_denied_without_contacting_the_endpoint(self):
        """``health_check`` keeps its never-raises contract and reports OFFLINE."""
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
        )
        health = provider.health_check()
        assert health.status == HealthStatus.OFFLINE
        assert "transmission" in health.detail.lower()

    def test_capability_probe_is_denied_without_contacting_the_endpoint(self):
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
        )
        probe = provider.capability_probe()
        assert probe.reachable is False
        assert "transmission" in probe.detail.lower()

    def test_provider_not_in_allow_list_is_denied(self):
        provider = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
            privacy_policy=open_policy(allowed_providers=frozenset({"someone_else"})),
        )
        with pytest.raises(SeraphimError) as exc:
            provider.generate(make_request())
        assert exc.value.sanitized_details["reason"] == REASON_PROVIDER_NOT_ALLOWED

    def test_local_only_policy_denies_external_and_allows_loopback(self):
        with loopback_server() as server:
            local = OpenAICompatibleProvider(
                OpenAICompatibleConfig(endpoint=base_url(server), model="m"),
                privacy_policy=PrivacyPolicy(local_only=True),
            )
            assert local.generate(make_request()).text() == "ok"
            assert local.last_privacy_decision.reason == REASON_LOCAL_PROVIDER
        remote = OpenAICompatibleProvider(
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m"),
            transport=ExplodingTransport(),
            privacy_policy=PrivacyPolicy(local_only=True),
        )
        with pytest.raises(SeraphimError):
            remote.generate(make_request())

    def test_loopback_endpoint_is_local_under_the_default_policy(self):
        """The offline suite and a local model keep working with no policy wired."""
        with loopback_server() as server:
            provider = OpenAICompatibleProvider(
                OpenAICompatibleConfig(endpoint=base_url(server), model="m")
            )
            assert provider.generate(make_request()).text() == "ok"
        assert provider.last_privacy_decision.reason == REASON_LOCAL_PROVIDER

    def test_factory_forwards_the_policy(self):
        entry = {
            "id": "m1",
            "provider": "openai_compatible",
            "model_name": "m",
            "endpoint": EXTERNAL,
        }
        denied = build_openai_compatible_provider(entry, transport=ExplodingTransport())
        with pytest.raises(SeraphimError) as exc:
            denied.generate(make_request())
        assert exc.value.code == ErrorCode.PRIVACY_TRANSMISSION_DENIED

        approved = build_openai_compatible_provider(
            entry, transport=RecordingTransport(), privacy_policy=open_policy()
        )
        assert approved.generate(make_request()).text() == "ok"


# ---------------------------------------------------------------------------
# D2: FakeProvider runs the same gate, as a local transfer
# ---------------------------------------------------------------------------


class TestFakeProviderGate:
    def test_fake_passes_the_default_deny_policy(self):
        provider = FakeProvider()
        assert provider.generate(make_request()).text() == "fake response"
        assert provider.last_privacy_decision.reason == REASON_LOCAL_PROVIDER

    def test_fake_passes_local_only_policy(self):
        provider = FakeProvider(privacy_policy=PrivacyPolicy(local_only=True))
        assert provider.generate(make_request()).text() == "fake response"

    def test_fake_streams_through_the_same_gate(self):
        provider = FakeProvider(
            capabilities=ProviderCapabilities(streaming=True),
            privacy_policy=PrivacyPolicy(),
        )
        events = list(provider.stream(make_request()))
        assert events
        assert provider.last_privacy_decision is not None
        assert provider.last_privacy_decision.allowed is True


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


class TestEndpointClassification:
    @pytest.mark.parametrize(
        "endpoint,expected",
        [
            ("http://127.0.0.1:11434", True),
            ("http://127.0.0.2:1234", True),
            ("http://localhost:1234", True),
            ("http://[::1]:1234", True),
            ("https://api.example.test", False),
            ("http://192.168.1.10:11434", False),
            ("http://10.0.0.5:8000", False),
            ("", False),
        ],
    )
    def test_only_loopback_counts_as_local(self, endpoint: str, expected: bool):
        assert endpoint_is_local(endpoint) is expected

    def test_categories_describe_context_without_payload(self):
        request = ModelRequest(
            messages=[
                Message.system("identity"),
                Message.user("question"),
                Message.tool_result("call_1", "output"),
            ],
            model="m",
        )
        categories = categories_for_request(request)
        assert "prompt" in categories
        assert "conversation" in categories
        assert "tool_output" in categories
        # Sorted: the same request always produces the same decision explanation.
        assert list(categories) == sorted(categories)

    def test_image_request_is_classified_as_images(self):
        from seraphim.model_layer import ImagePart

        request = ModelRequest(
            messages=[Message(role="user", content=[ImagePart(mime_type="image/png", data="AA")])],
            model="m",
        )
        assert "images" in categories_for_request(request)


# ---------------------------------------------------------------------------
# D9: an auth scheme the adapter cannot perform is a configuration error
# ---------------------------------------------------------------------------


class TestAuthSchemeValidation:
    @pytest.mark.parametrize("scheme", ["oauth", "local"])
    def test_unimplemented_scheme_is_rejected(self, scheme: str):
        with pytest.raises(SeraphimError) as exc:
            OpenAICompatibleConfig(endpoint=EXTERNAL, model="m", auth_scheme=scheme)
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert scheme in exc.value.safe_message

    @pytest.mark.parametrize("scheme", ["bearer", "api_key", "none"])
    def test_implemented_schemes_are_accepted(self, scheme: str):
        config = OpenAICompatibleConfig(endpoint=EXTERNAL, model="m", auth_scheme=scheme)
        assert config.auth_scheme == scheme

    def test_factory_rejects_an_unimplemented_scheme(self):
        with pytest.raises(SeraphimError) as exc:
            build_openai_compatible_provider(
                {
                    "id": "m1",
                    "provider": "openai_compatible",
                    "model_name": "m",
                    "endpoint": EXTERNAL,
                    "auth_scheme": "oauth",
                    "secret_ref": "provider.openai",
                }
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "oauth" in exc.value.safe_message

    def test_bearer_and_api_key_send_the_credential(self):
        """Rejecting oauth did not break the schemes that are implemented."""
        key = "sk-test-abcdefghijklmnopqrstuvwxyz0123456789"
        for scheme, header, expected in (
            ("bearer", "Authorization", f"Bearer {key}"),
            ("api_key", "X-Key", key),
        ):
            transport = RecordingTransport()
            provider = OpenAICompatibleProvider(
                OpenAICompatibleConfig(
                    endpoint=EXTERNAL,
                    model="m",
                    secret_ref="provider.test",
                    auth_scheme=scheme,
                    auth_header=header,
                ),
                secret_resolver=lambda ref: key,
                transport=transport,
                privacy_policy=open_policy(),
            )
            provider.generate(make_request())
            assert transport.calls[0]["headers"][header] == expected


# ---------------------------------------------------------------------------
# Loopback server (only for the "local endpoint" cases)
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:
        return

    def _reply(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        payload = json.dumps(COMPLETION).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _reply
    do_POST = _reply


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


@contextmanager
def loopback_server():
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: Any) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"
