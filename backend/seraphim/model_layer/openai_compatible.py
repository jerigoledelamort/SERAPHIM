# SERAPHIM MODEL LAYER — OpenAI-compatible HTTP provider adapter (S13).
#
# Goal: reach a *configured* OpenAI-compatible endpoint (spec §4.5, stage S13).
# Everything that distinguishes one endpoint from another — the URL, the paths,
# the auth scheme, the header carrying the key, the token-budget field and the
# set of supported features — is configuration.  There is no endpoint, model or
# feature hard-coded in this module, and no ``openai`` package is imported: the
# wire format is built and parsed explicitly so that a divergence is visible
# instead of hidden behind a vendor client.
#
# "OpenAI-compatible" is a family, not a spec.  This adapter therefore:
#   * assumes nothing about capabilities beyond ``chat`` (declared explicitly by
#     config, never inferred from a model name);
#   * treats every non-2xx status and every malformed body as a normalized
#     ``ProviderError``;
#   * tolerates the divergences that are known and cheap to detect (usage field
#     names, a missing tool-call id, a list-shaped message content) and reports
#     each one it had to work around in ``ModelResponse.metadata``;
#   * exposes a capability probe so a caller can see what was actually verified
#     rather than trusting a declaration.
#
# Not supported (documented limits, see IMPLEMENTATION_LOG S13 §10): streaming
# (S14), replaying assistant tool calls in the message history (the normalized
# ``Message`` has no assistant tool-call field yet — S14), embeddings/rerank
# endpoints, provider-specific extension fields beyond the ones named here.

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import (
    redact_known_secrets,
    register_known_secret,
    sanitize_dict,
    sanitize_text,
)
from seraphim.model_layer.cancellation import CancellationToken, run_with_cancellation
from seraphim.model_layer.capabilities import AuthKind, CapabilityFeature, ProviderCapabilities
from seraphim.model_layer.content import (
    ContentPart,
    ImagePart,
    Message,
    Role,
    TextPart,
    ToolResultPart,
)
from seraphim.model_layer.errors import (
    ProviderError,
    ProviderErrorKind,
    provider_cancelled_error,
    provider_rate_limited_error,
    provider_request_invalid_error,
    provider_response_invalid_error,
    provider_timeout_error,
    provider_unavailable_error,
)
from seraphim.model_layer.health import HealthStatus, ProviderHealth
from seraphim.model_layer.http_transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    HttpStream,
    HttpTransport,
    StreamIdle,
    UrllibTransport,
)
from seraphim.model_layer.provider import ModelProvider, ProviderHealthMixin
from seraphim.model_layer.request import ModelRequest
from seraphim.model_layer.response import (
    FinishReason,
    ModelResponse,
    ToolCall,
    Usage,
    normalize_tool_calls,
)
from seraphim.model_layer.sse import (
    SSEEventTooLargeError,
    SSEParser,
)
from seraphim.model_layer.stream import (
    RedactingDeltaBuffer,
    StreamEvent,
    StreamLimits,
    StreamSequencer,
)
from seraphim.model_layer.tool_calls import ToolCallAccumulator
from seraphim.model_layer.transmission import (
    decide_health_transmission,
    decide_transmission,
    endpoint_is_local,
    enforce_transmission,
)
from seraphim.sanctum.privacy import PrivacyDecision, PrivacyPolicy

logger = logging.getLogger("seraphim.model_layer.openai_compatible")

_COMPONENT = "model_layer.openai_compatible"

#: Health/probe request must never hang the doctor; it is capped independently of
#: the (usually larger) completion timeout.
PROBE_TIMEOUT_SECONDS = 10.0

#: Default output-token budget used by the factory when an entry does not set
#: ``max_tokens``.  It mirrors ``ModelEntry.max_tokens`` so that a raw config
#: mapping and a materialized ``ModelEntry`` behave identically.
_DEFAULT_MAX_TOKENS = 4096

#: ``Accept`` header sent for a streaming request.
STREAM_ACCEPT = "text/event-stream"

#: How long one ``read_line`` call waits before the loop re-checks cancellation,
#: the deadline and the idle timeout.  A short window keeps a cancel request
#: responsive without busy-spinning on a silent endpoint.
_STREAM_POLL_SECONDS = 0.05

#: Capabilities a caller may declare for an endpoint (config ``capabilities``).
#: ``auth`` is deliberately absent: it is derived from ``auth_scheme`` +
#: ``secret_ref`` so a config cannot claim an auth kind it does not use.
_BOOL_CAPABILITY_FIELDS = frozenset(
    {
        "streaming",
        "tool_calls",
        "vision",
        "structured_output",
        "reasoning_metadata",
        "supports_cancellation",
    }
)
_INT_CAPABILITY_FIELDS = frozenset({"context_limit", "max_output_tokens", "max_images"})

#: Features that a real exchange can actually demonstrate.  Only these appear in
#: a capability probe's ``verified`` set: a declaration for anything else is never
#: "verified".
_OBSERVABLE_FEATURES = frozenset(
    {
        CapabilityFeature.CHAT,
        CapabilityFeature.STREAMING,
        CapabilityFeature.TOOL_CALLS,
        CapabilityFeature.VISION,
        CapabilityFeature.STRUCTURED_OUTPUT,
    }
)

#: Endpoint features reported by a capability probe as *declared*.  Client-side
#: traits (``supports_cancellation``) are excluded: they describe this adapter,
#: not the endpoint, so reporting them as "unverified" would be noise.
_ENDPOINT_FEATURE_FIELDS = (
    "streaming",
    "tool_calls",
    "vision",
    "structured_output",
    "reasoning_metadata",
)

#: finish_reason values this adapter recognises.  An unrecognised value is kept
#: verbatim in the provider metadata block instead of being silently dropped.
_FINISH_REASON_MAP: dict[str, str] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "function_call": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}

#: Auth schemes this adapter can actually perform.  ``_build_headers`` writes a
#: static ``Bearer``/raw-value header, so only these three have an implementation;
#: ``oauth`` and ``local`` need a token exchange (or no credential at all in a way
#: the adapter cannot express yet).  Accepting them would let a configuration pass
#: validation while silently sending no credential (C5 review D9), so they are
#: rejected here rather than half-implemented.
_IMPLEMENTED_AUTH_SCHEMES = (AuthKind.BEARER, AuthKind.API_KEY, AuthKind.NONE)


def _validation(message: str) -> SeraphimError:
    return SeraphimError(
        code=ErrorCode.VALIDATION_FAILED,
        component=_COMPONENT,
        safe_message=message,
        user_action_required=True,
    )


def _as_int(value: Any) -> int:
    """Coerce a provider-reported counter to a non-negative int (0 otherwise)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class OpenAICompatibleConfig:
    """Everything needed to reach one OpenAI-compatible endpoint.

    Built from ``providers.models[]`` by :func:`build_openai_compatible_provider`;
    it can also be constructed directly (tests, LAB).  All defaults describe the
    most common shape and nothing more.
    """

    endpoint: str
    model: str
    provider_id: str = "openai_compatible"
    secret_ref: str = ""
    timeout_seconds: float = 30.0
    chat_path: str = "/v1/chat/completions"
    health_path: str = "/v1/models"
    auth_scheme: str = AuthKind.BEARER
    auth_header: str = "Authorization"
    extra_headers: dict[str, str] = field(default_factory=dict)
    #: Output-token budget sent when the request does not set one (0 = omit).
    #: Mirrors ``ModelEntry.max_tokens`` (single source: ``_DEFAULT_MAX_TOKENS``).
    max_tokens: int = _DEFAULT_MAX_TOKENS
    #: Request field carrying that budget ("max_tokens"/"max_completion_tokens").
    max_tokens_field: str = "max_tokens"
    #: JSON-schema name used for structured output.  Fixed in S13 (not exposed as
    #: a config field yet); the OpenAI ``json_schema`` shape is the only one sent.
    structured_output_name: str = "response"
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    #: Caps enforced while consuming a streamed response (S14).
    stream_limits: StreamLimits = field(default_factory=StreamLimits)
    #: Cap on a *non-streaming* response body.  A hostile or broken endpoint must
    #: not be able to make ``generate()`` allocate without bound (C5 review D6);
    #: this mirrors ``StreamLimits.max_response_bytes`` for the streaming path.
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    #: When true, ask the endpoint to include a ``usage`` object in the stream
    #: (OpenAI ``stream_options.include_usage``).  Off by default: a server that
    #: does not know the field could reject the request, and a usage event is only
    #: ever emitted when the endpoint actually reported one.
    stream_include_usage: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint.strip():
            raise _validation(
                "providers.models[].endpoint must be set: the endpoint is configuration, "
                "not a source constant"
            )
        if not isinstance(self.model, str) or not self.model.strip():
            raise _validation("providers.models[].model_name must be set")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise _validation(
                f"timeout_seconds must be positive, got {self.timeout_seconds!r}"
            )
        if self.auth_scheme not in _IMPLEMENTED_AUTH_SCHEMES:
            raise _validation(
                f"auth_scheme {self.auth_scheme!r} is not one of "
                f"{[kind.value for kind in _IMPLEMENTED_AUTH_SCHEMES]}: this adapter "
                f"builds a static credential header; oauth/local require a token "
                f"flow this adapter does not implement, and accepting them would "
                f"silently send no credential at all"
            )
        if not isinstance(self.auth_header, str) or not self.auth_header.strip():
            raise _validation("auth_header must be a non-empty header name")
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int):
            raise _validation(f"max_tokens must be an int, got {self.max_tokens!r}")
        if self.max_tokens < 0:
            raise _validation(f"max_tokens must not be negative, got {self.max_tokens}")
        if not isinstance(self.capabilities, ProviderCapabilities):
            raise _validation("capabilities must be a ProviderCapabilities instance")
        if not isinstance(self.stream_limits, StreamLimits):
            raise _validation("stream_limits must be a StreamLimits instance")
        if not isinstance(self.stream_include_usage, bool):
            raise _validation(
                f"stream_include_usage must be a bool, got {self.stream_include_usage!r}"
            )
        if isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int) or self.max_response_bytes <= 0:
            raise _validation(
                f"max_response_bytes must be a positive int, got {self.max_response_bytes!r}"
            )
        self.extra_headers = _validate_headers(self.extra_headers)
        # A path must be a *path*: an absolute URL here would send the request
        # (and the credential header) to a host the endpoint does not name.
        for name, value in (("chat_path", self.chat_path), ("health_path", self.health_path)):
            if not isinstance(value, str) or "://" in value or value.startswith("//"):
                raise _validation(
                    f"{name} must be a relative path appended to endpoint, got {value!r}"
                )

        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in ("http", "https"):
            raise _validation(
                f"endpoint must be an absolute http(s) URL, got scheme {parsed.scheme!r}"
            )
        if not parsed.netloc:
            raise _validation("endpoint must include a host")
        if parsed.username or parsed.password:
            raise _validation(
                "endpoint must not embed credentials; store the value with "
                "'seraphim secrets set <ref>' and reference it with secret_ref"
            )

    # -- Derived -------------------------------------------------------------

    @property
    def auth_kind(self) -> str:
        """Auth kind implied by the configured scheme and presence of a key."""
        if not self.secret_ref or self.auth_scheme == AuthKind.NONE:
            return AuthKind.NONE
        return self.auth_scheme

    def chat_url(self) -> str:
        return _join_url(self.endpoint, self.chat_path)

    def health_url(self) -> str:
        return _join_url(self.endpoint, self.health_path)

    def to_dict(self) -> dict[str, Any]:
        """Safe description (no credential, no header values).

        Sanitized again on the way out: a dump method is a sink, so a value that
        reached a field by mistake must not be able to leave through it.
        """
        return sanitize_dict(
            {
                "provider_id": self.provider_id,
                "endpoint": _safe_endpoint(self.endpoint),
                "model": self.model,
                "chat_path": self.chat_path,
                "health_path": self.health_path,
                "auth_scheme": str(self.auth_scheme),
                "auth_header": self.auth_header,
                "secret_ref": self.secret_ref,
                "timeout_seconds": self.timeout_seconds,
                "max_tokens": self.max_tokens,
                "max_tokens_field": self.max_tokens_field,
                "extra_header_names": sorted(self.extra_headers),
                "capabilities": self.capabilities.to_dict(),
                "stream_limits": self.stream_limits.to_dict(),
                "stream_include_usage": self.stream_include_usage,
            }
        )


def _validate_headers(headers: Any) -> dict[str, str]:
    """Validate ``extra_headers`` and refuse a literal credential.

    A header value is sent verbatim on every request, so it is the one transport
    field that could carry a key.  A value that looks like a credential is
    rejected here as well as in the config loader: a config may reach this code
    through a path that bypassed the loader.  Control characters are refused too
    — a bare ``\r``/``\n`` would otherwise surface as an un-normalized
    ``ValueError`` deep inside ``http.client``.
    """
    if not isinstance(headers, dict):
        raise _validation("extra_headers must be a mapping of header name to value")
    cleaned: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not name.strip():
            raise _validation("extra_headers keys must be non-empty header names")
        if not isinstance(value, str):
            raise _validation(f"extra_headers[{name}] must be a string")
        if _has_control_characters(name) or _has_control_characters(value):
            raise _validation(f"extra_headers[{name}] must not contain control characters")
        if sanitize_text(value) != value:
            raise _validation(
                f"extra_headers[{name}] looks like a literal secret; use secret_ref instead"
            )
        cleaned[name] = value
    return cleaned


def _has_control_characters(value: str) -> bool:
    return any(character in "\r\n\x00" for character in value)


def _join_url(endpoint: str, path: str) -> str:
    """Append *path* to *endpoint* (an absolute path overrides the base path)."""
    if not path:
        return endpoint
    if "://" in path:
        return path
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


def _safe_endpoint(endpoint: str) -> str:
    """Endpoint with any userinfo removed (defence in depth; see config check)."""
    scheme, sep, rest = endpoint.partition("://")
    if not sep:
        return endpoint
    host_and_path = rest.split("/", 1)
    host = host_and_path[0].split("@")[-1]
    tail = f"/{host_and_path[1]}" if len(host_and_path) > 1 else ""
    return f"{scheme}://{host}{tail}"


# ---------------------------------------------------------------------------
# Capability probe result
# ---------------------------------------------------------------------------


@dataclass
class CapabilityProbe:
    """What was *actually verified* about an endpoint.

    ``verified`` holds only features observed in a real exchange; ``declared``
    holds what the configuration claims.  ``unverified_declared`` is the gap —
    the honest answer to "is this endpoint really tool-calling capable?".
    """

    reachable: bool = False
    status: int | None = None
    verified: frozenset[str] = frozenset()
    declared: frozenset[str] = frozenset()
    unverified_declared: frozenset[str] = frozenset()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "status": self.status,
            # Plain strings, not enum members: this dict is a serialization sink.
            "verified": sorted(str(feature) for feature in self.verified),
            "declared": sorted(str(feature) for feature in self.declared),
            "unverified_declared": sorted(str(feature) for feature in self.unverified_declared),
            "detail": sanitize_text(self.detail),
        }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(ModelProvider, ProviderHealthMixin):
    """Adapter for a configured OpenAI-compatible chat endpoint.

    Args:
        config: Endpoint, model, auth and declared capabilities.
        secret_resolver: ``ref -> value`` callable (usually
            ``SecretStore.get``).  Called lazily, once per request, so the value
            is read only when it is about to be used.  Never stored.
        transport: HTTP seam.  Defaults to :class:`UrllibTransport`; a test
            injects a fake so no socket is opened.
    """

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        secret_resolver: Callable[[str], str] | None = None,
        transport: HttpTransport | None = None,
        privacy_policy: PrivacyPolicy | None = None,
    ) -> None:
        self.config = config
        # ``provider_id`` reaches the error envelope and the response metadata,
        # so a value pasted into the config by mistake is scrubbed first.
        self.provider_id = sanitize_text(config.provider_id) or "openai_compatible"
        self.model = config.model
        self._secret_resolver = secret_resolver
        self._transport: HttpTransport = (
            transport
            if transport is not None
            else UrllibTransport(
                provider_id=self.provider_id,
                max_response_bytes=self.config.max_response_bytes,
            )
        )
        # Features observed in a real exchange (see ``capability_probe``).
        self._verified: set[str] = set()
        # Privacy gate: deny-by-default when no operator-approved policy was wired.
        # A loopback endpoint is local, so the deny gate does not block loopback
        # tests — an external endpoint *is* blocked unless the user supplies a
        # policy that allows it.  CONTRACTS.md §6.4, spec §4.5, TB-9.
        self._external = not endpoint_is_local(config.endpoint)
        self._privacy_policy: PrivacyPolicy | None = privacy_policy
        self.last_privacy_decision: PrivacyDecision | None = None

    # -- Declaration ---------------------------------------------------------

    def declared_capabilities(self) -> ProviderCapabilities:
        """Capabilities the configuration states (never inferred)."""
        return self.config.capabilities

    def verified_capabilities(self) -> ProviderCapabilities:
        """Only the features observed in a real exchange."""
        return _restrict(self.config.capabilities, self._verified)

    def get_capabilities(self) -> ProviderCapabilities:
        """Capabilities published to CORE/COMPASS.

        This is the *explicit declaration* from configuration, never an inference
        from the model name: an empty declaration publishes ``chat`` only.  A
        declaration is a statement by the operator, not proof — a consumer that
        needs proof uses :meth:`verified_capabilities` or
        :meth:`capability_probe`, which report only features a real exchange
        demonstrated.
        """
        return self.config.capabilities

    # -- Health --------------------------------------------------------------

    def health_check(self) -> ProviderHealth:
        """Probe the configured health path.  Never raises."""
        started = time.monotonic()
        try:
            response = self._probe_request()
        except SeraphimError as exc:
            return self._health(
                HealthStatus.OFFLINE,
                started_at=started,
                detail=getattr(exc, "safe_message", "") or str(exc),
                metadata={"error_code": getattr(exc, "code", "")},
            )
        except Exception as exc:  # pragma: no cover - defensive: health must not raise
            return self._health(
                HealthStatus.OFFLINE,
                started_at=started,
                detail=f"health probe failed: {type(exc).__name__}",
            )

        status = response.status
        if 200 <= status < 300:
            return self._health(HealthStatus.ONLINE, started_at=started, detail="endpoint reachable")
        if status in (401, 403):
            return self._health(
                HealthStatus.DEGRADED,
                started_at=started,
                detail=f"endpoint reachable but rejected the credential (HTTP {status})",
                metadata={"status": status, "secret_ref": self.config.secret_ref},
            )
        if status >= 500:
            return self._health(
                HealthStatus.DEGRADED,
                started_at=started,
                detail=f"endpoint reachable but returned HTTP {status}",
                metadata={"status": status},
            )
        return self._health(
            HealthStatus.DEGRADED,
            started_at=started,
            detail=(
                f"endpoint reachable but the health path returned HTTP {status} "
                f"(check providers.models[].health_path)"
            ),
            metadata={"status": status},
        )

    def capability_probe(self) -> CapabilityProbe:
        """Report what is verified about the endpoint.  Never raises."""
        declared = _feature_set(self.config.capabilities)
        try:
            response = self._probe_request()
        except SeraphimError as exc:
            return CapabilityProbe(
                reachable=False,
                status=None,
                verified=frozenset(self._verified_features()),
                declared=frozenset(declared),
                unverified_declared=frozenset(declared - self._verified),
                detail=getattr(exc, "safe_message", "") or str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive: a probe must not raise
            return CapabilityProbe(
                reachable=False,
                status=None,
                verified=frozenset(self._verified_features()),
                declared=frozenset(declared),
                unverified_declared=frozenset(declared - self._verified),
                detail=f"capability probe failed: {type(exc).__name__}",
            )
        return CapabilityProbe(
            reachable=True,
            status=response.status,
            verified=frozenset(self._verified_features()),
            declared=frozenset(declared),
            unverified_declared=frozenset(declared - self._verified),
            detail=(
                "endpoint reachable; only observed features are listed as verified"
                if response.status < 400
                else f"reachable, health path returned HTTP {response.status}"
            ),
        )

    def _verified_features(self) -> set[str]:
        """Observed features, restricted to the ones an exchange can demonstrate."""
        return {feature for feature in self._verified if feature in _OBSERVABLE_FEATURES}

    # -- Generation ----------------------------------------------------------

    # -- Pre-flight ----------------------------------------------------------

    def validate_request(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> None:
        """Reject a request the endpoint cannot satisfy.

        Beyond the base capability checks, this adapter validates that the request
        targets the model this provider was built for: the payload field
        ``model`` is configuration (``providers.models[].model_name``), so a
        request carrying a different model would either be silently rewritten
        (CORE asked for A, the endpoint got B) or send an arbitrary string to the
        server.  Selecting a different model means selecting a different config
        entry, which is COMPASS's job (S15), not a per-request override.
        """
        super().validate_request(request, cancellation)
        if request.model and request.model != self.config.model:
            raise provider_request_invalid_error(
                self.provider_id,
                safe_message=(
                    f"request asks for model {request.model!r} but this provider is "
                    f"configured for {self.config.model!r}; point the request at the "
                    f"providers.models[] entry that has that model"
                ),
            )

    def generate(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> ModelResponse:
        # Privacy gate: before any request reaches the endpoint, the policy
        # must approve the transfer (CONTRACTS.md §6.4, spec §4.5, TB-9).
        self.last_privacy_decision = decide_transmission(
            self._privacy_policy,
            self.provider_id,
            request,
            model=self.config.model,
            purpose="chat",
            external=self._external,
        )
        enforce_transmission(self.last_privacy_decision)
        # Capability gate first: an unsupported feature must be a normalized
        # capability error, not a provider-specific 400.
        self.validate_request(request, cancellation)
        if cancellation is not None:
            cancellation.raise_if_cancelled(self.provider_id)

        key = self._resolve_secret()
        payload = self._build_payload(request)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self._build_headers(key)
        url = self.config.chat_url()
        timeout = request.timeout_seconds or self.config.timeout_seconds

        self._log(
            logging.INFO,
            "chat request",
            host=_safe_endpoint(self.config.endpoint),
            model=self.config.model,
            messages=len(request.messages),
            tools=len(request.tools),
        )

        response = run_with_cancellation(
            lambda: self._transport.request(
                "POST", url, headers=headers, body=body, timeout=timeout
            ),
            cancellation,
            self.provider_id,
        )

        if response.status >= 400:
            raise self._http_error(response, key)
        if response.status >= 300:
            # The transport refuses to follow redirects (a redirect would resend
            # the credential header to another host), so a 3xx arrives here.
            raise self._redirect_error(response)

        parsed = self._parse_response(response)
        self._record_observation(request, parsed)
        return parsed

    # -- Streaming -----------------------------------------------------------

    def stream(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream a completion as normalized events (S14).

        The pre-flight checks (declared ``streaming`` capability, request
        validation, an already-cancelled token) run *before* the generator is
        created, so a caller that made an unsupported request learns immediately
        instead of receiving a stream that fails on the first ``next()``.

        After ``START`` every failure is delivered as a terminal event
        (``ERROR``/``CANCELLED``) rather than raised: CORE and the UI consume one
        uniform event stream and never have to interleave ``try/except`` with
        iteration.  A consumer that stops early still closes the connection (the
        generator's ``finally`` runs on ``close()``/GC).
        """
        caps = self.get_capabilities()
        caps.require(CapabilityFeature.STREAMING, self.provider_id)
        # Privacy gate in the pre-flight, before START: a denied context must not
        # produce a stream that then fails, and the credential is never resolved.
        self.last_privacy_decision = decide_transmission(
            self._privacy_policy,
            self.provider_id,
            request,
            model=self.config.model,
            purpose="stream",
            external=self._external,
        )
        enforce_transmission(self.last_privacy_decision)
        self.validate_request(request, cancellation)
        if cancellation is not None:
            cancellation.raise_if_cancelled(self.provider_id)
        return self._stream_events(request, cancellation)

    def _stream_events(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None,
    ) -> Iterator[StreamEvent]:
        sequencer = StreamSequencer(self.provider_id)
        limits = self.config.stream_limits
        timeout = request.timeout_seconds or self.config.timeout_seconds
        yield sequencer.start(
            metadata={
                "provider": self.provider_id,
                "model": self.config.model,
                "stream": True,
            }
        )

        stream: HttpStream | None = None
        try:
            try:
                key = self._resolve_secret()
                body = json.dumps(
                    self._build_payload(request, stream=True), ensure_ascii=False
                ).encode("utf-8")
                headers = self._build_headers(key)
                headers["Accept"] = STREAM_ACCEPT
                self._log(
                    logging.INFO,
                    "stream request",
                    host=_safe_endpoint(self.config.endpoint),
                    model=self.config.model,
                    messages=len(request.messages),
                    tools=len(request.tools),
                )
                stream = self._transport.open_stream(
                    "POST", self.config.chat_url(), headers=headers, body=body, timeout=timeout
                )
            except SeraphimError as exc:
                # Includes a normalized transport failure and a missing secret.
                yield sequencer.error(exc)
                return

            try:
                yield from self._pump_stream(
                    stream, sequencer, limits, key, timeout, request, cancellation
                )
            except Exception as exc:
                # Defensive: a failure that was not normalized (a bug, a
                # third-party transport, an unserializable payload) must still end
                # the stream with a terminal event, because a consumer relies on
                # "exactly one terminal event, always last".  Only the exception
                # *type* is reported — a raw message is untrusted text.
                if not sequencer.terminated:
                    yield sequencer.error(
                        provider_response_invalid_error(
                            self.provider_id,
                            safe_message=f"stream failed: {type(exc).__name__}",
                        )
                    )
                return
        finally:
            if stream is not None:
                stream.close()

    def _pump_stream(
        self,
        stream: HttpStream,
        sequencer: StreamSequencer,
        limits: StreamLimits,
        key: str,
        timeout: float,
        request: ModelRequest,
        cancellation: CancellationToken | None,
    ) -> Iterator[StreamEvent]:
        """Read the response and emit every event up to and including the terminal one."""
        if stream.status >= 400:
            yield sequencer.error(self._http_error(stream, key))
            return
        if stream.status >= 300:
            # Same rule as the non-streaming path: the credential must not follow
            # a redirect to a host the operator never configured.
            yield sequencer.error(self._redirect_error(stream))
            return

        parser = SSEParser(max_event_bytes=limits.max_event_bytes)
        accumulator = ToolCallAccumulator(self.provider_id, limits=limits.tool_call_limits())
        started_calls: set[int] = set()
        # Live deltas pass through a hold-back buffer so a credential split across
        # two fragments is never emitted in pieces (S14 review finding M2).
        text_buffer = RedactingDeltaBuffer()
        argument_buffers: dict[int, RedactingDeltaBuffer] = {}
        raw_text: list[str] = []
        usage = Usage()
        usage_reported = False
        finish_reason = ""
        response_id = ""
        response_model = ""
        saw_data = False
        saw_done = False
        total_bytes = 0

        now = time.monotonic()
        deadline = now + timeout
        idle_deadline = now + limits.idle_timeout_seconds
        stream_ended = False

        while True:
            if cancellation is not None and cancellation.is_cancelled:
                yield sequencer.cancelled(provider_cancelled_error(self.provider_id))
                return
            now = time.monotonic()
            if now >= deadline:
                yield sequencer.error(
                    provider_timeout_error(
                        self.provider_id,
                        safe_message=(
                            f"stream from {_safe_endpoint(self.config.endpoint)} exceeded the "
                            f"{timeout}s timeout"
                        ),
                    )
                )
                return
            if now >= idle_deadline:
                yield sequencer.error(
                    provider_timeout_error(
                        self.provider_id,
                        safe_message=(
                            f"stream from {_safe_endpoint(self.config.endpoint)} was idle for "
                            f"more than {limits.idle_timeout_seconds}s"
                        ),
                    )
                )
                return

            if stream_ended:
                message = parser.close()
            else:
                try:
                    line = stream.read_line(_STREAM_POLL_SECONDS)
                except StreamIdle:
                    continue
                except ProviderError as exc:
                    yield sequencer.error(exc)
                    return
                if line is None:
                    stream_ended = True
                    continue
                idle_deadline = time.monotonic() + limits.idle_timeout_seconds
                # Counted on the decoded line re-encoded as UTF-8: an invalid byte
                # becomes a 3-byte replacement character, so the count can only
                # overstate the body, never understate it (a hostile endpoint
                # cannot slip past the cap by sending malformed UTF-8).
                total_bytes += len(line.encode("utf-8", errors="replace"))
                if total_bytes > limits.max_response_bytes:
                    yield sequencer.error(
                        provider_response_invalid_error(
                            self.provider_id,
                            safe_message=(
                                f"streamed response exceeds {limits.max_response_bytes} bytes"
                            ),
                            retryable=False,
                        )
                    )
                    return
                try:
                    message = parser.feed_line(line)
                except SSEEventTooLargeError as exc:
                    yield sequencer.error(
                        provider_response_invalid_error(
                            self.provider_id, safe_message=str(exc), retryable=False
                        )
                    )
                    return

            if message is None:
                if stream_ended:
                    break
                continue
            if message.is_done:
                saw_done = True
                break
            saw_data = True

            chunk_error = None
            try:
                chunk = json.loads(message.data)
            except ValueError:
                chunk = None
                chunk_error = "streamed chunk is not valid JSON"
            if chunk_error is None and not isinstance(chunk, dict):
                chunk_error = "streamed chunk is not a JSON object"
            if chunk_error is not None:
                yield sequencer.error(
                    provider_response_invalid_error(
                        self.provider_id, safe_message=chunk_error, retryable=False
                    )
                )
                return

            if isinstance(chunk.get("id"), str) and chunk["id"]:
                response_id = sanitize_text(chunk["id"])
            if isinstance(chunk.get("model"), str) and chunk["model"]:
                response_model = sanitize_text(chunk["model"])
            if isinstance(chunk.get("usage"), dict):
                usage = _parse_usage(chunk["usage"])
                usage_reported = True

            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue

            delta = choice.get("delta")
            if isinstance(delta, dict):
                text = _delta_text(delta.get("content"))
                if text:
                    raw_text.append(text)
                    # Emit a best-effort scrubbed delta for the UI through a
                    # hold-back buffer, so a credential split across two chunks is
                    # never emitted in halves (S14 review finding M2).  The
                    # authoritative, fully scrubbed text is assembled below.
                    safe = text_buffer.feed(text)
                    if safe:
                        yield sequencer.text_delta(safe)
                for index, call_id, name, args_delta in _delta_tool_calls(
                    delta.get("tool_calls")
                ):
                    try:
                        accumulator.feed(
                            index=index,
                            call_id=call_id,
                            name=name,
                            arguments_delta=args_delta,
                        )
                    except ProviderError as exc:
                        yield sequencer.error(exc)
                        return
                    # START is announced the first time an index is seen, and
                    # always *before* any argument fragment for it: a consumer
                    # must never receive arguments for a call it was not told
                    # about.  The id/name may still be empty here — a server is
                    # allowed to send arguments first — and the authoritative
                    # values arrive in the final TOOL_CALL event.
                    if index not in started_calls:
                        started_calls.add(index)
                        # The id/name are untrusted server data and an event is a
                        # sink, so they are scrubbed before they reach one.
                        yield sequencer.tool_call_start(
                            index, sanitize_text(call_id), sanitize_text(name)
                        )
                    if args_delta:
                        # The accumulator keeps the raw fragment (so the JSON
                        # still parses); the emitted event carries a scrubbed
                        # copy, because an event is a log/UI sink.  The hold-back
                        # buffer stops a secret split across fragments from
                        # leaking in halves (S14 review finding M2).
                        buffer = argument_buffers.setdefault(index, RedactingDeltaBuffer())
                        safe = buffer.feed(args_delta)
                        if safe:
                            yield sequencer.tool_call_args_delta(index, safe)

            raw_finish = choice.get("finish_reason")
            if isinstance(raw_finish, str) and raw_finish:
                finish_reason = raw_finish

        if not saw_data and not saw_done:
            # The endpoint closed (or went silent) without sending a single event
            # and without the end-of-stream sentinel: it is not speaking SSE.
            yield sequencer.error(
                provider_response_invalid_error(
                    self.provider_id,
                    safe_message="stream closed before any event arrived",
                    retryable=False,
                )
            )
            return

        try:
            calls = accumulator.finish()
        except ProviderError as exc:
            # A truncated or malformed argument payload is rejected here, so an
            # incomplete tool call is never emitted and never executed.
            yield sequencer.error(exc)
            return

        # Release whatever the hold-back buffers kept: the stream is complete
        # here, so a credential can no longer be split and the tail is safe to
        # emit.  (On an error or cancel path the tail is deliberately dropped
        # rather than flushed, so a truncated credential never escapes.)
        tail = text_buffer.flush()
        if tail:
            yield sequencer.text_delta(tail)
        for index in sorted(argument_buffers):
            tail = argument_buffers[index].flush()
            if tail:
                yield sequencer.tool_call_args_delta(index, tail)

        for index, call in zip(accumulator.pending_indexes, calls, strict=True):
            yield sequencer.tool_call(call, index)
        if usage_reported:
            yield sequencer.usage(usage)

        text = sanitize_text("".join(raw_text))
        finish, finish_known = _map_finish_reason(finish_reason or None)
        if calls and finish == FinishReason.STOP:
            finish = FinishReason.TOOL_CALLS
        response = ModelResponse(
            id=response_id or f"{self.provider_id}_response",
            model=response_model or self.config.model,
            provider=self.provider_id,
            content=[TextPart(text)] if text else [],
            tool_calls=calls,
            finish_reason=finish,
            usage=usage,
            metadata={
                "provider": {
                    self.provider_id: {
                        # The same keys the non-streaming path reports, plus the
                        # ones only a stream can know, so a consumer reads the
                        # metadata identically whichever path produced it.
                        "streamed": True,
                        "saw_done_sentinel": saw_done,
                        "finish_reason_raw": finish_reason,
                        "unknown_finish_reason": not finish_known,
                        "synthesized_tool_call_ids": accumulator.synthesized_ids,
                    }
                }
            },
        )
        self._verified.add(CapabilityFeature.STREAMING)
        self._record_observation(request, response)
        yield sequencer.done(response)

    # -- Internals -----------------------------------------------------------

    def _probe_request(self) -> Any:
        # A probe sends the credential, so it is gated too: an endpoint the policy
        # does not allow is never contacted, not even to ask whether it is alive.
        self.last_privacy_decision = decide_health_transmission(
            self._privacy_policy,
            self.provider_id,
            model=self.config.model,
            external=self._external,
        )
        enforce_transmission(self.last_privacy_decision)
        headers = self._build_headers(self._resolve_secret())
        timeout = min(self.config.timeout_seconds, PROBE_TIMEOUT_SECONDS)
        return self._transport.request(
            "GET", self.config.health_url(), headers=headers, body=None, timeout=timeout
        )

    def _resolve_secret(self) -> str:
        """Read the credential for this request, or return ``""``.

        The value is read lazily and registered with the process-wide redactor so
        it cannot be written back into a log, an error or an export even if the
        resolver did not register it.
        """
        ref = self.config.secret_ref
        if not ref:
            return ""
        if self._secret_resolver is None:
            raise SeraphimError(
                code=ErrorCode.SECRET_NOT_FOUND,
                component=_COMPONENT,
                safe_message=(
                    f"model entry references secret '{ref}' but no secret store is "
                    f"available to this provider"
                ),
                user_action_required=True,
                details={"secret_ref": ref},
            )
        value = self._secret_resolver(ref)
        if value:
            register_known_secret(value)
        return value

    def _build_headers(self, key: str) -> dict[str, str]:
        """Build request headers.

        Extra headers are applied first so that the credential header always wins
        and a config cannot shadow it with a literal value.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        for name, value in self.config.extra_headers.items():
            headers[name] = value
        if key and self.config.auth_scheme == AuthKind.BEARER:
            headers[self.config.auth_header] = f"Bearer {key}"
        elif key and self.config.auth_scheme == AuthKind.API_KEY:
            headers[self.config.auth_header] = key
        return headers

    def _build_payload(self, request: ModelRequest, *, stream: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [_encode_message(message) for message in request.messages],
            "stream": stream,
        }
        if stream and self.config.stream_include_usage:
            # Only when the operator asked for it: a server that does not know
            # the field could reject the request, and usage is optional.
            payload["stream_options"] = {"include_usage": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p

        max_tokens = request.max_output_tokens or self.config.max_tokens
        if max_tokens and self.config.max_tokens_field:
            payload[self.config.max_tokens_field] = max_tokens

        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
                for tool in request.tools
            ]
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": self.config.structured_output_name,
                    "schema": request.response_schema,
                },
            }
        return payload

    def _redirect_error(self, response: Any) -> ProviderError:
        """Refuse a redirect.

        Following it would resend the ``Authorization`` header to whatever host
        the response names, i.e. send the credential somewhere the operator never
        configured.  The ``Location`` value is deliberately not echoed (it can
        carry a query string).
        """
        return provider_request_invalid_error(
            self.provider_id,
            safe_message=(
                f"endpoint answered with a redirect (HTTP {response.status}); SERAPHIM does "
                f"not follow redirects because the credential header would be sent to "
                f"another host. Point providers.models[].endpoint at the final URL."
            ),
        )

    def _http_error(self, response: Any, key: str) -> ProviderError:
        """Map an HTTP error status onto a normalized provider error.

        The provider's own error text is used only after it has been scrubbed: a
        gateway that echoes the credential in its error body must not be able to
        push it into a SERAPHIM error, log or diagnostic dump.
        """
        status = response.status
        detail = self._error_detail(response, key)
        suffix = f": {detail}" if detail else ""
        if status in (401, 403):
            return ProviderError(
                ProviderErrorKind.AUTH,
                self.provider_id,
                safe_message=(
                    f"endpoint rejected the credential (HTTP {status}){suffix}"
                ),
                details={
                    "status": status,
                    "secret_ref": self.config.secret_ref,
                    "endpoint": _safe_endpoint(self.config.endpoint),
                },
            )
        if status == 408:
            return provider_timeout_error(
                self.provider_id,
                safe_message=f"endpoint timed out (HTTP {status}){suffix}",
            )
        if status == 429:
            return provider_rate_limited_error(
                self.provider_id,
                safe_message=f"endpoint rate limited the request (HTTP {status}){suffix}",
            )
        if status >= 500:
            return provider_unavailable_error(
                self.provider_id,
                safe_message=f"endpoint returned HTTP {status}{suffix}",
            )
        return provider_request_invalid_error(
            self.provider_id,
            safe_message=(
                f"endpoint rejected the request (HTTP {status}){suffix}"
            ),
        )

    def _error_detail(self, response: Any, key: str) -> str:
        """Extract a short, scrubbed reason from an error body."""
        try:
            data = response.json()
        except (ValueError, AttributeError):
            return ""
        detail = ""
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = error["message"]
            elif isinstance(error, str):
                detail = error
            elif isinstance(data.get("message"), str):
                detail = data["message"]
        detail = sanitize_text(detail)[:200]
        if key:
            detail = redact_known_secrets(detail, key)
        return detail

    def _parse_response(self, response: Any) -> ModelResponse:
        """Turn an untrusted response body into a normalized ``ModelResponse``.

        Every value taken from the body passes through the sanitizer before it
        becomes a contract field.  A model response is untrusted data (TB-1) and
        the endpoint has just seen the credential in a header, so a server that
        echoes it back — in ``id``, ``model``, ``content`` or a tool call — must
        not be able to place it in a response that CORE will serialize, log or
        show (S13 review finding BLOCKER B1).
        """
        try:
            data = response.json()
        except ValueError:
            raise provider_response_invalid_error(
                self.provider_id,
                safe_message="endpoint returned a body that is not valid JSON",
            ) from None
        if not isinstance(data, dict):
            raise provider_response_invalid_error(
                self.provider_id,
                safe_message="endpoint returned a JSON value that is not an object",
            )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise provider_response_invalid_error(
                self.provider_id,
                safe_message="response has no 'choices' array (not a chat completion)",
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise provider_response_invalid_error(
                self.provider_id, safe_message="'choices[0]' is not an object"
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            raise provider_response_invalid_error(
                self.provider_id,
                safe_message=(
                    "'choices[0].message' is missing (legacy text-completion shape is "
                    "not supported)"
                ),
            )

        content = _extract_content(message.get("content"), provider_id=self.provider_id)
        tool_calls, synthesized = _extract_tool_calls(message.get("tool_calls"), self.provider_id)

        raw_finish = choice.get("finish_reason")
        finish_reason, finish_known = _map_finish_reason(raw_finish)
        if tool_calls and finish_reason == FinishReason.STOP:
            finish_reason = FinishReason.TOOL_CALLS

        provider_metadata: dict[str, Any] = {
            # The same keys the streaming path reports, so a consumer reads the
            # metadata identically whichever path produced the response.
            "streamed": False,
            "finish_reason_raw": raw_finish if isinstance(raw_finish, str) else "",
            "unknown_finish_reason": not finish_known,
            # A compatible server omitted a tool-call id; one was synthesized so
            # the call can be answered.  Reported, never hidden.
            "synthesized_tool_call_ids": synthesized,
        }
        fingerprint = data.get("system_fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            provider_metadata["system_fingerprint"] = sanitize_text(fingerprint)

        response_model = data.get("model")
        response_id = data.get("id")
        return ModelResponse(
            id=self._response_id(response_id),
            model=(
                sanitize_text(response_model)
                if isinstance(response_model, str) and response_model
                else self.config.model
            ),
            provider=self.provider_id,
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=_parse_usage(data.get("usage")),
            metadata={"provider": {self.provider_id: provider_metadata}},
        )

    def _response_id(self, raw: Any) -> str:
        """Return a sanitized response id, or a deterministic fallback.

        A deterministic id (never random) keeps a golden dump reproducible when a
        server omits ``id``.
        """
        if isinstance(raw, str) and raw:
            return sanitize_text(raw)
        return f"{self.provider_id}_response"

    def _record_observation(self, request: ModelRequest, response: ModelResponse) -> None:
        """Record features a *response* demonstrated, not features a request asked for.

        A request carrying an image or a schema proves only what the caller wanted;
        the endpoint proves something only through what it sent back.  So:

        * ``chat`` — a completion object came back;
        * ``tool_calls`` — the response actually contained tool calls;
        * ``structured_output`` — a schema was requested *and* the text parses as a
          JSON object (a plain-text answer to a schema request is not structured
          output);
        * ``vision`` and ``reasoning_metadata`` are never recorded here.  An
          endpoint that accepts an image part without an error has not demonstrated
          that it read the image, and nothing in this adapter parses reasoning
          fields; both stay "declared but unverified" until there is real evidence.
        """
        self._verified.add(CapabilityFeature.CHAT)
        if response.tool_calls:
            self._verified.add(CapabilityFeature.TOOL_CALLS)
        if request.response_schema is not None and _is_json_object_text(response.text()):
            self._verified.add(CapabilityFeature.STRUCTURED_OUTPUT)

    def _log(self, level: int, message: str, **fields: Any) -> None:
        """Log a sanitized line.  Header values and the credential are never passed."""
        if not logger.isEnabledFor(level):
            return
        safe_fields = {name: sanitize_text(str(value)) for name, value in fields.items()}
        rendered = " ".join(f"{name}={value}" for name, value in safe_fields.items())
        logger.log(level, "%s: %s", message, rendered)


def _is_json_object_text(text: str) -> bool:
    """Whether *text* is a JSON object — the evidence a schema request needs.

    The adapter does not validate against the schema (that is the caller's job);
    it only checks that the answer is JSON-shaped at all.  A prose reply to a
    ``response_format`` request is not structured output, so recording it as
    verified would be an overclaim (C5 review D3).
    """
    if not text:
        return False
    try:
        return isinstance(json.loads(text), dict)
    except (json.JSONDecodeError, ValueError):
        return False


def _restrict(base: ProviderCapabilities, verified: set[str]) -> ProviderCapabilities:
    """Return *base* with every optional feature that was not observed disabled."""
    return replace(
        base,
        chat=base.chat and CapabilityFeature.CHAT in verified,
        streaming=base.streaming and CapabilityFeature.STREAMING in verified,
        tool_calls=base.tool_calls and CapabilityFeature.TOOL_CALLS in verified,
        vision=base.vision and CapabilityFeature.VISION in verified,
        structured_output=(
            base.structured_output and CapabilityFeature.STRUCTURED_OUTPUT in verified
        ),
        reasoning_metadata=(
            base.reasoning_metadata and CapabilityFeature.REASONING_METADATA in verified
        ),
    )


def _feature_set(capabilities: ProviderCapabilities) -> set[str]:
    """Names of the endpoint features *capabilities* declares.

    Includes features that cannot be observed (``reasoning_metadata``) so that a
    probe reports them as declared-but-unverified rather than silently dropping
    them.
    """
    declared = {
        name for name in _ENDPOINT_FEATURE_FIELDS if bool(getattr(capabilities, name, False))
    }
    if capabilities.chat:
        declared.add(CapabilityFeature.CHAT)
    return declared


def _encode_message(message: Message) -> dict[str, Any]:
    """Encode one normalized message into the OpenAI chat message shape.

    Divergences handled explicitly: a tool message carries its result in
    ``content`` plus ``tool_call_id``; a message with images becomes a list of
    ``text``/``image_url`` parts (only reached when ``vision`` is declared, since
    ``validate_request`` gates it).
    """
    text_parts = [part for part in message.content if isinstance(part, TextPart)]
    images = [part for part in message.content if isinstance(part, ImagePart)]
    results = [part for part in message.content if isinstance(part, ToolResultPart)]

    if message.role == Role.TOOL or results:
        content = "\n".join(part.content for part in results)
        if not content:
            content = "".join(part.text for part in text_parts)
        encoded: dict[str, Any] = {"role": str(Role.TOOL), "content": content}
        call_id = message.tool_call_id or (results[0].tool_call_id if results else "")
        if call_id:
            encoded["tool_call_id"] = call_id
        if message.name:
            encoded["name"] = message.name
        return encoded

    if images:
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": part.text} for part in text_parts if part.text
        ]
        parts.extend(
            {"type": "image_url", "image_url": {"url": _image_url(image)}} for image in images
        )
        encoded = {"role": str(message.role), "content": parts}
    else:
        encoded = {"role": str(message.role), "content": "".join(p.text for p in text_parts)}
    if message.tool_calls:
        # An assistant turn that requested tools must replay those calls, or the
        # following ``tool`` result refers to a call the server never saw (D7).
        encoded["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    if message.name:
        encoded["name"] = message.name
    return encoded


def _image_url(image: ImagePart) -> str:
    """Turn an ``ImagePart`` into a URL a compatible endpoint accepts.

    Inline base64 data wins when present; otherwise the reference is passed as a
    URL.  No provider-specific encoding leaks into the message contract.
    """
    if image.data:
        return f"data:{image.mime_type};base64,{image.data}"
    return image.data_ref


def _delta_text(raw: Any) -> str:
    """Extract the text of a streaming ``delta.content`` field.

    A compatible server may send the content as a plain string (the common
    shape) or as a list of parts.  Anything else contributes no text.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _delta_tool_calls(raw: Any) -> Iterator[tuple[int, str, str, str]]:
    """Yield ``(index, id, name, arguments_delta)`` from a streaming tool-call delta.

    Only the fields that carry correlation are extracted; a missing or
    non-integer ``index`` becomes ``-1`` so the accumulator rejects it instead of
    guessing which call a fragment belongs to.
    """
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            index = -1
        call_id = entry.get("id")
        name = ""
        arguments = ""
        function = entry.get("function")
        if isinstance(function, dict):
            raw_name = function.get("name")
            name = raw_name if isinstance(raw_name, str) else ""
            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, str):
                arguments = raw_arguments
            elif raw_arguments is not None:
                # The protocol streams the arguments as a JSON *string* fragment,
                # but some compatible servers send the already-parsed object.
                # Serializing it keeps the payload instead of silently dropping it
                # (which would run the tool with empty arguments); a malformed or
                # cumulatively repeated object is then rejected by the
                # accumulator rather than ignored (S14 review finding m1).
                arguments = json.dumps(raw_arguments, ensure_ascii=False)
        yield (
            index,
            call_id if isinstance(call_id, str) else "",
            name,
            arguments,
        )


def _extract_content(raw: Any, provider_id: str = "") -> list[ContentPart]:
    """Normalize ``message.content`` into text parts.

    A plain string is the common shape; a list of parts appears on some
    vision-capable compatible servers.  ``None`` (a pure tool-call turn) yields
    no text parts.  Any other shape is a malformed response, not an empty answer:
    silently returning ``[]`` for, say, a ``{"text": "hi"}`` object would make the
    caller see a blank reply and act on it (C5 review D10).  Every text is
    sanitized: it is untrusted server data.
    """
    if isinstance(raw, str):
        return [TextPart(sanitize_text(raw))] if raw else []
    if isinstance(raw, list):
        parts: list[ContentPart] = []
        for item in raw:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(TextPart(sanitize_text(text)))
            elif isinstance(item, str) and item:
                parts.append(TextPart(sanitize_text(item)))
        return parts
    if raw is None:
        return []
    raise provider_response_invalid_error(
        provider_id,
        safe_message=f"'message.content' must be a string, a list or null, got {type(raw).__name__}",
    )


def _extract_tool_calls(raw: Any, provider_id: str) -> tuple[list[ToolCall], bool]:
    """Normalize the OpenAI ``tool_calls`` array into ``ToolCall`` objects.

    Returns the calls plus whether any id had to be synthesized (a known
    divergence: some compatible servers omit ``id``).  Names, ids and argument
    payloads are sanitized before they become contract fields — a tool call is
    untrusted data and must not be a channel for the credential the endpoint just
    received in a header.
    """
    if raw is None or raw == []:
        return [], False
    if not isinstance(raw, list):
        raise provider_response_invalid_error(
            provider_id, safe_message="'message.tool_calls' is not an array"
        )
    flattened: list[dict[str, Any]] = []
    synthesized = False
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise provider_response_invalid_error(
                provider_id, safe_message=f"tool call #{index} is not an object"
            )
        function = entry.get("function")
        function = function if isinstance(function, dict) else {}
        call_id = entry.get("id") or entry.get("tool_call_id") or ""
        if not isinstance(call_id, str) or not call_id:
            call_id = f"{provider_id}_call_{index}"
            synthesized = True
        name = function.get("name") or entry.get("name") or ""
        if not isinstance(name, str):
            raise provider_response_invalid_error(
                provider_id,
                safe_message=f"tool call #{index} has a non-string function name",
            )
        arguments = function.get("arguments", entry.get("arguments", {}))
        flattened.append(
            {
                "id": sanitize_text(call_id),
                "name": sanitize_text(name) if isinstance(name, str) else name,
                "arguments": _sanitize_arguments(arguments),
            }
        )
    return normalize_tool_calls(flattened, provider_id), synthesized


def _sanitize_arguments(arguments: Any) -> Any:
    """Scrub a tool-call argument payload (object or JSON string)."""
    if isinstance(arguments, dict):
        return sanitize_dict(arguments)
    if isinstance(arguments, str):
        return sanitize_text(arguments)
    return arguments


def _map_finish_reason(raw: Any) -> tuple[str, bool]:
    """Map a provider finish_reason; ``(reason, known)``."""
    if isinstance(raw, str):
        mapped = _FINISH_REASON_MAP.get(raw.strip().lower())
        if mapped is not None:
            return mapped, True
    return FinishReason.STOP, raw is None or raw == ""


def _parse_usage(raw: Any) -> Usage:
    """Parse ``usage``, accepting both OpenAI and Anthropic-style field names."""
    if not isinstance(raw, dict):
        return Usage()
    prompt = _as_int(raw.get("prompt_tokens", raw.get("input_tokens", 0)))
    completion = _as_int(raw.get("completion_tokens", raw.get("output_tokens", 0)))
    total = _as_int(raw.get("total_tokens", 0))
    cached = 0
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached = _as_int(details.get("cached_tokens", 0))
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
    )


# ---------------------------------------------------------------------------
# Factory: configuration -> provider
# ---------------------------------------------------------------------------


def build_openai_compatible_provider(
    entry: Mapping[str, Any] | Any,
    *,
    secret_resolver: Callable[[str], str] | None = None,
    transport: HttpTransport | None = None,
    privacy_policy: PrivacyPolicy | None = None,
) -> OpenAICompatibleProvider:
    """Build a provider from one ``providers.models[]`` entry.

    *entry* may be a raw mapping (how the loader leaves a config) or a
    ``ModelEntry``.  Nothing about the endpoint is taken from source code: the
    URL, the paths, the auth scheme, the headers, the token-budget field and the
    declared capabilities all come from *entry*.

    ``privacy_policy`` is the SANCTUM policy that must approve every outbound
    transfer.  Leaving it ``None`` is the safe choice, not the permissive one: the
    provider then runs on the deny-by-default policy, so only a loopback (local)
    endpoint can be reached.  CORE/COMPASS pass the operator-approved policy.
    """
    endpoint = _entry_str(entry, "endpoint")
    model = _entry_str(entry, "model_name") or _entry_str(entry, "model")
    provider_id = _entry_str(entry, "provider") or "openai_compatible"
    secret_ref = _entry_str(entry, "secret_ref")
    auth_scheme = _entry_str(entry, "auth_scheme") or AuthKind.BEARER
    capabilities = _capabilities_from_entry(entry, auth_scheme=auth_scheme, secret_ref=secret_ref)

    config = OpenAICompatibleConfig(
        endpoint=endpoint,
        model=model,
        provider_id=provider_id,
        secret_ref=secret_ref,
        timeout_seconds=_entry_float(entry, "timeout_seconds", 30.0),
        chat_path=_entry_str(entry, "chat_path") or "/v1/chat/completions",
        health_path=_entry_str(entry, "health_path") or "/v1/models",
        auth_scheme=auth_scheme,
        auth_header=_entry_str(entry, "auth_header") or "Authorization",
        extra_headers=dict(_entry_mapping(entry, "extra_headers")),
        max_tokens=_entry_int(entry, "max_tokens", _DEFAULT_MAX_TOKENS),
        max_tokens_field=(
            _entry_str(entry, "max_tokens_field")
            if _has_key(entry, "max_tokens_field")
            else "max_tokens"
        ),
        capabilities=capabilities,
        stream_limits=_stream_limits_from_entry(entry),
        max_response_bytes=_entry_positive_int(
            entry, "max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES
        ),
        stream_include_usage=bool(_entry_raw(entry, "stream_include_usage", False)),
    )
    return OpenAICompatibleProvider(
        config,
        secret_resolver=secret_resolver,
        transport=transport,
        privacy_policy=privacy_policy,
    )


def _stream_limits_from_entry(entry: Mapping[str, Any] | Any) -> StreamLimits:
    """Build ``StreamLimits`` from the ``providers.models[]`` entry.

    Every field is optional and falls back to the ``StreamLimits`` default, so an
    entry written before S14 keeps working unchanged.  A non-positive value is a
    configuration error rather than a silently disabled cap.
    """
    defaults = StreamLimits()
    limits = StreamLimits(
        max_response_bytes=_entry_positive_int(
            entry, "stream_max_response_bytes", defaults.max_response_bytes
        ),
        max_event_bytes=_entry_positive_int(
            entry, "stream_max_event_bytes", defaults.max_event_bytes
        ),
        max_arguments_bytes=_entry_positive_int(
            entry, "stream_max_arguments_bytes", defaults.max_arguments_bytes
        ),
        max_tool_calls=_entry_positive_int(
            entry, "stream_max_tool_calls", defaults.max_tool_calls
        ),
        idle_timeout_seconds=_entry_positive_float(
            entry, "stream_idle_timeout_seconds", defaults.idle_timeout_seconds
        ),
    )
    return limits


def _capabilities_from_entry(
    entry: Mapping[str, Any] | Any, *, auth_scheme: str, secret_ref: str
) -> ProviderCapabilities:
    """Build ``ProviderCapabilities`` from an explicit config declaration.

    An empty declaration means "chat only": the adapter never assumes that an
    OpenAI-compatible endpoint supports tools, vision, structured output or
    streaming.  ``auth`` is derived from the configured scheme, not declared.
    """
    declared = _entry_mapping(entry, "capabilities")
    unknown = sorted(set(declared) - (_BOOL_CAPABILITY_FIELDS | _INT_CAPABILITY_FIELDS | {"labels"}))
    if unknown:
        raise _validation(
            f"providers.models[].capabilities has unknown feature(s): {', '.join(unknown)}. "
            f"Known features: "
            f"{', '.join(sorted(_BOOL_CAPABILITY_FIELDS | _INT_CAPABILITY_FIELDS))}, labels"
        )

    bools: dict[str, Any] = {
        name: bool(declared[name]) for name in _BOOL_CAPABILITY_FIELDS if name in declared
    }
    ints: dict[str, Any] = {
        name: _coerce_int(declared[name], name)
        for name in _INT_CAPABILITY_FIELDS
        if name in declared
    }
    labels = declared.get("labels", ())
    if not isinstance(labels, (list, tuple)) or not all(isinstance(x, str) for x in labels):
        raise _validation("providers.models[].capabilities.labels must be a list of strings")

    auth = AuthKind.NONE if not secret_ref or auth_scheme == AuthKind.NONE else auth_scheme
    return ProviderCapabilities(
        chat=True,
        labels=tuple(labels),
        auth=auth,
        **bools,
        **ints,
    )


def _coerce_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _validation(f"providers.models[].capabilities.{name} must be a non-negative int")
    return value


def _has_key(entry: Mapping[str, Any] | Any, key: str) -> bool:
    if isinstance(entry, Mapping):
        return key in entry
    return hasattr(entry, key)


def _entry_raw(entry: Mapping[str, Any] | Any, key: str, default: Any) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _entry_str(entry: Mapping[str, Any] | Any, key: str) -> str:
    value = _entry_raw(entry, key, "")
    return value if isinstance(value, str) else ""


def _entry_mapping(entry: Mapping[str, Any] | Any, key: str) -> dict[str, Any]:
    value = _entry_raw(entry, key, {})
    return dict(value) if isinstance(value, dict) else {}


def _entry_int(entry: Mapping[str, Any] | Any, key: str, default: int) -> int:
    value = _entry_raw(entry, key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _entry_positive_int(entry: Mapping[str, Any] | Any, key: str, default: int) -> int:
    """Read a positive int from *entry*; reject a declared non-positive value."""
    if not _has_key(entry, key):
        return default
    value = _entry_raw(entry, key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _validation(f"providers.models[].{key} must be a positive int, got {value!r}")
    return value


def _entry_positive_float(entry: Mapping[str, Any] | Any, key: str, default: float) -> float:
    """Read a positive number from *entry*; reject a declared non-positive value."""
    if not _has_key(entry, key):
        return default
    value = _entry_raw(entry, key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise _validation(f"providers.models[].{key} must be positive, got {value!r}")
    return float(value)


def _entry_float(entry: Mapping[str, Any] | Any, key: str, default: float) -> float:
    value = _entry_raw(entry, key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "STREAM_ACCEPT",
    "CapabilityProbe",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "build_openai_compatible_provider",
]
