# SERAPHIM MODEL LAYER — provider interface (S12).
#
# A provider is the single seam between SERAPHIM and any model endpoint.  CORE,
# COMPASS and the rest of the system depend on this interface only; a concrete
# provider (OpenAI-compatible, local server, fake) implements it without any
# CORE change (spec §4.5, CONTRACTS.md §3.2 rule 7: MODEL LAYER does not depend
# on CORE/COMPASS).

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from seraphim.contracts.errors import SeraphimError
from seraphim.model_layer.cancellation import CancellationToken
from seraphim.model_layer.capabilities import CapabilityFeature, ProviderCapabilities
from seraphim.model_layer.errors import (
    ProviderError,
    provider_request_invalid_error,
    provider_response_invalid_error,
)
from seraphim.model_layer.health import HealthStatus, ProviderHealth
from seraphim.model_layer.request import ModelRequest
from seraphim.model_layer.response import ModelResponse
from seraphim.model_layer.stream import StreamEvent, StreamSequencer


class ModelProvider(ABC):
    """Abstract provider interface.

    Implementations declare their capabilities explicitly via
    :meth:`get_capabilities`.  Capabilities are never inferred from the model
    name: an implementation that cannot know a feature must report it as
    unsupported.
    """

    #: Stable provider identifier (e.g. ``"fake"``, ``"openai_compatible"``).
    provider_id: str = ""

    # -- Declaration ---------------------------------------------------------

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Return the provider's declared capabilities."""

    def capabilities(self) -> ProviderCapabilities:
        """Alias for :meth:`get_capabilities` (readability at call-sites)."""
        return self.get_capabilities()

    def verified_capabilities(self) -> ProviderCapabilities:
        """Capabilities confirmed by observation; nothing is verified by default."""
        return ProviderCapabilities()

    # -- Health --------------------------------------------------------------

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Probe availability.  Must not raise: failures map to OFFLINE/DEGRADED."""

    # -- Generation ----------------------------------------------------------

    @abstractmethod
    def generate(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> ModelResponse:
        """Run one completion.  Raises :class:`ProviderError` on failure."""

    def stream(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[StreamEvent]:
        """Stream a completion as normalized events.

        The base implementation is a deterministic stub: it requires the
        ``streaming`` capability, runs the blocking :meth:`generate`, and emits
        the whole response as a single terminal ``DONE`` event (never fake
        incremental deltas).  It builds its events through :class:`StreamSequencer`
        so the ordering contract holds for every provider, not only for the ones
        that implement real streaming.  A failure from :meth:`generate` is
        reported as a terminal ``ERROR`` event, never as an exception: a consumer
        of the event stream relies on "exactly one terminal event, always last",
        and only the capability gate (which runs before ``START``) may raise.
        """
        caps = self.get_capabilities()
        caps.require(CapabilityFeature.STREAMING, self.provider_id)
        self.validate_request(request, cancellation)
        sequencer = StreamSequencer(self.provider_id)
        yield sequencer.start()
        try:
            response = self.generate(request, cancellation)
        except SeraphimError as exc:
            yield sequencer.error(exc)
            return
        except Exception as exc:
            # A non-normalized failure (a bug in the provider) must still
            # terminate the stream; only the exception *type* is reported, since
            # a raw message is untrusted text.
            yield sequencer.error(
                provider_response_invalid_error(
                    self.provider_id,
                    safe_message=f"stream failed: {type(exc).__name__}",
                )
            )
            return
        yield sequencer.done(response)

    # -- Pre-flight ----------------------------------------------------------

    def validate_request(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> None:
        """Reject a request the declared capabilities cannot satisfy.

        This runs *before* any provider work so that an unsupported feature is a
        normalized capability error, not a provider-specific failure.  Passing a
        cancellation token to a provider that did not declare cancellation
        support is itself a capability violation.
        """
        caps = self.get_capabilities()
        caps.require(CapabilityFeature.CHAT, self.provider_id)
        if request.stream:
            caps.require(CapabilityFeature.STREAMING, self.provider_id)
        if request.tools:
            caps.require(CapabilityFeature.TOOL_CALLS, self.provider_id)
        if request.response_schema is not None:
            caps.require(CapabilityFeature.STRUCTURED_OUTPUT, self.provider_id)
        if cancellation is not None:
            caps.require(CapabilityFeature.CANCELLATION, self.provider_id)
        if request.has_images():
            caps.require(CapabilityFeature.VISION, self.provider_id)
            if caps.max_images and len(request.images()) > caps.max_images:
                raise provider_request_invalid_error(
                    self.provider_id,
                    safe_message=(
                        f"request has {len(request.images())} images but provider allows "
                        f"at most {caps.max_images}"
                    ),
                )
        if caps.context_limit and request.estimated_prompt_tokens() > caps.context_limit:
            raise provider_request_invalid_error(
                self.provider_id,
                safe_message=(
                    f"estimated prompt tokens {request.estimated_prompt_tokens()} exceed "
                    f"context limit {caps.context_limit}"
                ),
            )
        if (
            request.max_output_tokens is not None
            and caps.max_output_tokens
            and request.max_output_tokens > caps.max_output_tokens
        ):
            raise provider_request_invalid_error(
                self.provider_id,
                safe_message=(
                    f"requested max_output_tokens {request.max_output_tokens} exceed "
                    f"provider maximum {caps.max_output_tokens}"
                ),
            )


class ProviderHealthMixin:
    """Small helper for providers that probe a local, non-raising health check."""

    provider_id: str = ""
    model: str = ""

    def _health(
        self,
        status: str,
        *,
        started_at: float | None = None,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ProviderHealth:
        latency = None
        if started_at is not None:
            latency = round((time.monotonic() - started_at) * 1000, 3)
        return ProviderHealth(
            status=status,
            provider_id=self.provider_id,
            model=self.model,
            latency_ms=latency,
            detail=detail,
            metadata=metadata or {},
        )

    def _health_from_error(self, error: ProviderError) -> ProviderHealth:
        status = HealthStatus.OFFLINE
        if error.retryable:
            status = HealthStatus.DEGRADED
        return ProviderHealth(
            status=status,
            provider_id=self.provider_id,
            model=self.model,
            detail=error.safe_message,
            metadata={"error_code": error.code},
        )


__all__ = ["ModelProvider", "ProviderHealthMixin"]
