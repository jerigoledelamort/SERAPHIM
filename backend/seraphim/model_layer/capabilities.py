# SERAPHIM MODEL LAYER — provider capability declaration (S12).
#
# A provider declares what it actually supports (spec §4.5).  Capabilities are
# NEVER inferred from a model name: there is deliberately no ``from_model_name``
# helper and no field that is derived from the name.  A request that needs a
# feature the provider did not declare is rejected before any work happens.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer.errors import provider_capability_error


class AuthKind(StrEnum):
    """How a provider authenticates.  The value is a *kind*, not a secret."""

    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH = "oauth"
    LOCAL = "local"


class CapabilityFeature(StrEnum):
    """Named, provider-independent features a request can require."""

    CHAT = "chat"
    STREAMING = "streaming"
    TOOL_CALLS = "tool_calls"
    VISION = "vision"
    STRUCTURED_OUTPUT = "structured_output"
    REASONING_METADATA = "reasoning_metadata"
    CANCELLATION = "cancellation"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Explicit, declared capabilities of a provider/model.

    Every field is stated by the provider implementation (and later by config,
    S15) — never guessed from the model id.  ``context_limit`` and
    ``max_output_tokens`` use ``0`` to mean "unknown/unbounded".
    """

    chat: bool = True
    streaming: bool = False
    tool_calls: bool = False
    vision: bool = False
    structured_output: bool = False
    reasoning_metadata: bool = False
    context_limit: int = 0
    max_output_tokens: int = 0
    max_images: int = 0
    auth: str = AuthKind.NONE
    supports_cancellation: bool = True
    # Free-form, non-behavioural labels for UI/COMPASS (e.g. modality names).
    # They must NOT be used to enable a feature — the boolean fields above are
    # the single source of truth.
    labels: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.auth, str) or self.auth not in set(AuthKind):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.capabilities",
                safe_message=(
                    f"Invalid auth kind: {self.auth!r}. Must be one of "
                    f"{[a.value for a in AuthKind]}"
                ),
            )
        for name in ("context_limit", "max_output_tokens", "max_images"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SeraphimError(
                    code=ErrorCode.VALIDATION_FAILED,
                    component="model_layer.capabilities",
                    safe_message=f"{name} must be a non-negative int, got {value!r}",
                )

    # -- Queries -------------------------------------------------------------

    def supports(self, feature: str) -> bool:
        """Return whether *feature* is declared.

        ``cancellation`` is answered by ``supports_cancellation``; unknown
        features are treated as unsupported rather than assumed.
        ``reasoning_metadata`` is a provider-reported trait that COMPASS may use
        for routing; there is no request field that *requires* it, so it is not
        checked by ``ModelProvider.validate_request`` (S12).
        """
        if feature == CapabilityFeature.CANCELLATION:
            return self.supports_cancellation
        return bool(getattr(self, feature, False)) if feature in set(CapabilityFeature) else False

    def require(self, feature: str, provider_id: str = "") -> None:
        """Raise a normalized capability error if *feature* is not declared."""
        if not self.supports(feature):
            raise provider_capability_error(provider_id, feature)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat": self.chat,
            "streaming": self.streaming,
            "tool_calls": self.tool_calls,
            "vision": self.vision,
            "structured_output": self.structured_output,
            "reasoning_metadata": self.reasoning_metadata,
            "context_limit": self.context_limit,
            "max_output_tokens": self.max_output_tokens,
            "max_images": self.max_images,
            "auth": self.auth,
            "supports_cancellation": self.supports_cancellation,
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderCapabilities:
        return cls(
            chat=data.get("chat", True),
            streaming=data.get("streaming", False),
            tool_calls=data.get("tool_calls", False),
            vision=data.get("vision", False),
            structured_output=data.get("structured_output", False),
            reasoning_metadata=data.get("reasoning_metadata", False),
            context_limit=data.get("context_limit", 0),
            max_output_tokens=data.get("max_output_tokens", 0),
            max_images=data.get("max_images", 0),
            auth=data.get("auth", AuthKind.NONE),
            supports_cancellation=data.get("supports_cancellation", True),
            labels=tuple(data.get("labels", ())),
        )
