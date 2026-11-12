# MODEL LAYER (S12) — provider abstraction and offline fake provider.
#
# Layer 4 per CONTRACTS.md §3.1: depends only on CONTRACTS and SANCTUM, never on
# CORE/COMPASS/WINGS.  Public surface is provider-agnostic: capabilities,
# normalized request/response, cancellation, timeout, usage and normalized
# provider errors.

from seraphim.model_layer.cancellation import CancellationToken, run_with_cancellation
from seraphim.model_layer.capabilities import (
    AuthKind,
    CapabilityFeature,
    ProviderCapabilities,
)
from seraphim.model_layer.content import (
    ContentPart,
    ImagePart,
    Message,
    PartKind,
    Role,
    TextPart,
    ToolResultPart,
    part_from_dict,
)
from seraphim.model_layer.errors import (
    KIND_DEFAULTS,
    KIND_TO_CODE,
    ProviderError,
    ProviderErrorKind,
    provider_auth_error,
    provider_cancelled_error,
    provider_capability_error,
    provider_rate_limited_error,
    provider_request_invalid_error,
    provider_response_invalid_error,
    provider_timeout_error,
    provider_unavailable_error,
)
from seraphim.model_layer.fake import FakeProvider, FakeTurn
from seraphim.model_layer.health import HealthStatus, ProviderHealth
from seraphim.model_layer.http_transport import (
    DEFAULT_MAX_LINE_BYTES,
    DEFAULT_USER_AGENT,
    HttpResponse,
    HttpStream,
    HttpTransport,
    StreamIdle,
    UrllibTransport,
)
from seraphim.model_layer.openai_compatible import (
    PROBE_TIMEOUT_SECONDS,
    STREAM_ACCEPT,
    CapabilityProbe,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    build_openai_compatible_provider,
)
from seraphim.model_layer.provider import ModelProvider, ProviderHealthMixin
from seraphim.model_layer.request import ModelRequest, ToolSpec
from seraphim.model_layer.response import (
    FinishReason,
    ModelResponse,
    ToolCall,
    Usage,
    normalize_tool_calls,
)
from seraphim.model_layer.sse import (
    DEFAULT_MAX_EVENT_BYTES,
    STREAM_DONE_SENTINEL,
    SSEEventTooLargeError,
    SSEMessage,
    SSEParser,
)
from seraphim.model_layer.stream import (
    TERMINAL_EVENT_TYPES,
    RedactingDeltaBuffer,
    StreamEvent,
    StreamEventType,
    StreamLimits,
    StreamSequencer,
    validate_stream,
)
from seraphim.model_layer.tool_calls import ToolCallAccumulator, ToolCallLimits
from seraphim.model_layer.transmission import (
    categories_for_request,
    decide_health_transmission,
    decide_transmission,
    describe_privacy,
    endpoint_is_local,
    enforce_transmission,
    transmission_request,
)
from seraphim.sanctum.privacy import PrivacyDecision, PrivacyPolicy, TransmissionRequest

__all__ = [
    "DEFAULT_MAX_EVENT_BYTES",
    "DEFAULT_MAX_LINE_BYTES",
    "DEFAULT_USER_AGENT",
    "KIND_DEFAULTS",
    "KIND_TO_CODE",
    "PROBE_TIMEOUT_SECONDS",
    "STREAM_ACCEPT",
    "STREAM_DONE_SENTINEL",
    "TERMINAL_EVENT_TYPES",
    "AuthKind",
    "CancellationToken",
    "CapabilityFeature",
    "CapabilityProbe",
    "ContentPart",
    "FakeProvider",
    "FakeTurn",
    "FinishReason",
    "HealthStatus",
    "HttpResponse",
    "HttpStream",
    "HttpTransport",
    "ImagePart",
    "Message",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "PartKind",
    "PrivacyDecision",
    "PrivacyPolicy",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderErrorKind",
    "ProviderHealth",
    "ProviderHealthMixin",
    "RedactingDeltaBuffer",
    "Role",
    "SSEEventTooLargeError",
    "SSEMessage",
    "SSEParser",
    "StreamEvent",
    "StreamEventType",
    "StreamIdle",
    "StreamLimits",
    "StreamSequencer",
    "TextPart",
    "ToolCall",
    "ToolCallAccumulator",
    "ToolCallLimits",
    "ToolResultPart",
    "ToolSpec",
    "TransmissionRequest",
    "UrllibTransport",
    "Usage",
    "build_openai_compatible_provider",
    "categories_for_request",
    "decide_health_transmission",
    "decide_transmission",
    "describe_privacy",
    "endpoint_is_local",
    "enforce_transmission",
    "normalize_tool_calls",
    "part_from_dict",
    "provider_auth_error",
    "provider_cancelled_error",
    "provider_capability_error",
    "provider_rate_limited_error",
    "provider_request_invalid_error",
    "provider_response_invalid_error",
    "provider_timeout_error",
    "provider_unavailable_error",
    "run_with_cancellation",
    "transmission_request",
    "validate_stream",
]
