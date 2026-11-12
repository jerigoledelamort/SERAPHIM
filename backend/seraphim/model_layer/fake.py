# SERAPHIM MODEL LAYER — deterministic offline FakeProvider (S12).
#
# Purpose: let agent/CORE tests run fully offline and reproducibly (spec §20.1
# contract tests, golden scenario §20.2 #1).  The fake provider performs no I/O
# at all: no sockets, no files, no random values.  Response identifiers, tool
# call identifiers and turn ordering are deterministic, so tests can assert
# exact values.  Timestamps default to the wall clock (a response needs a real
# ``created_at``); pass ``fixed_created_at`` for a byte-for-byte golden dump.
#
# Supported behaviours: success, tool calls, refusal/content filter, normalized
# failure, timeout and cancellation.

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from seraphim.model_layer.cancellation import CancellationToken
from seraphim.model_layer.capabilities import ProviderCapabilities
from seraphim.model_layer.content import ContentPart, TextPart
from seraphim.model_layer.errors import (
    ProviderError,
    ProviderErrorKind,
    provider_timeout_error,
)
from seraphim.model_layer.health import HealthStatus, ProviderHealth
from seraphim.model_layer.provider import ModelProvider, ProviderHealthMixin
from seraphim.model_layer.request import ModelRequest
from seraphim.model_layer.response import (
    FinishReason,
    ModelResponse,
    ToolCall,
    Usage,
    normalize_tool_calls,
)
from seraphim.model_layer.transmission import decide_transmission, enforce_transmission
from seraphim.sanctum.privacy import PrivacyDecision, PrivacyPolicy

#: Cooperative cancellation poll interval (seconds).  Small enough to keep
#: cancellation tests fast; the value only matters when a delay is scripted.
_CANCEL_POLL_SECONDS = 0.01


@dataclass
class FakeTurn:
    """One scripted provider turn.

    Exactly one behaviour is used, in this precedence order:
    ``error_kind`` → raise; ``tool_calls`` → tool-call response;
    ``text`` → text response (``finish_reason`` may be ``refusal``).
    """

    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = FinishReason.STOP
    usage: Usage | None = None
    #: When set, the turn raises a normalized ProviderError of this kind.
    error_kind: str = ""
    error_message: str = ""
    #: Simulated latency before the turn resolves (interruptible by cancel).
    delay_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [dict(c) for c in self.tool_calls],
            "finish_reason": self.finish_reason,
            "usage": self.usage.to_dict() if self.usage else None,
            "error_kind": self.error_kind,
            "error_message": self.error_message,
            "delay_seconds": self.delay_seconds,
        }


class FakeProvider(ModelProvider, ProviderHealthMixin):
    """A deterministic, offline provider implementation.

    Args:
        provider_id: Stable id reported in responses and errors.
        model: Model id echoed in responses.
        capabilities: Declared capabilities (defaults to a chat-only provider,
            i.e. the conservative assumption — a fake does not get features it
            was not explicitly given).
        script: Ordered turns returned by successive :meth:`generate` calls.
            When the script is exhausted, ``default_text`` is returned.
        default_text: Fallback text for calls beyond the script.
        health_status: Status returned by :meth:`health_check`.
        sleep: When ``False``, scripted delays are skipped (kept for tests that
            must not spend wall-clock time). Cancellation still works.
    """

    def __init__(
        self,
        provider_id: str = "fake",
        model: str = "fake-model",
        *,
        capabilities: ProviderCapabilities | None = None,
        script: list[FakeTurn] | None = None,
        default_text: str = "fake response",
        health_status: str = HealthStatus.ONLINE,
        sleep: bool = True,
        fixed_created_at: str = "",
        privacy_policy: PrivacyPolicy | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.model = model
        self._capabilities = capabilities if capabilities is not None else ProviderCapabilities()
        self._script = list(script or [])
        self._initial_script = list(script or [])
        self._default_text = default_text
        self._health_status = health_status
        self._sleep = sleep
        # When set, responses carry this timestamp instead of the wall clock so
        # that a golden comparison of a full response dump is reproducible.
        self._fixed_created_at = fixed_created_at
        # Deterministic counters (never uuid/random) so assertions are stable.
        self._call_index = 0
        self._response_index = 0
        self._tool_call_index = 0
        self.last_request: ModelRequest | None = None
        # The privacy gate runs for a fake too, as a *local* transfer: nothing
        # leaves the machine, so even a ``local_only`` policy must not break
        # offline agent tests, while the decision is still recorded for CORE
        # (C5 review D2).
        self._privacy_policy = privacy_policy
        self.last_privacy_decision: PrivacyDecision | None = None

    # -- Declaration ---------------------------------------------------------

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def verified_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    # -- Health --------------------------------------------------------------

    def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        return self._health(self._health_status, started_at=started, detail="fake provider")

    # -- Control -------------------------------------------------------------

    def enqueue(self, turn: FakeTurn) -> None:
        """Append a turn to the script."""
        self._script.append(turn)

    def reset(self) -> None:
        """Reset counters, ``last_request`` and the script to its initial state."""
        self._call_index = 0
        self._response_index = 0
        self._tool_call_index = 0
        self.last_request = None
        self._script = list(self._initial_script)

    # -- Generation ----------------------------------------------------------

    def generate(
        self,
        request: ModelRequest,
        cancellation: CancellationToken | None = None,
    ) -> ModelResponse:
        # Privacy gate: a fake performs no transmission, so this is recorded as a
        # *local* transfer — always allowed, even under ``local_only``, which is
        # what keeps offline agent tests working while the decision is still
        # visible to the caller (C5 review D2).
        self.last_privacy_decision = decide_transmission(
            self._privacy_policy,
            self.provider_id,
            request,
            model=self.model,
            purpose="chat",
            external=False,
        )
        enforce_transmission(self.last_privacy_decision)
        self.validate_request(request, cancellation)
        # Record the attempt (including a cancelled one) for test assertions.
        self.last_request = request

        # Cancellation is checked before counters or the script are consumed, so
        # a cancelled call does not advance ids or swallow a scripted turn.
        if cancellation is not None and cancellation.is_cancelled:
            cancellation.raise_if_cancelled(self.provider_id)

        call_index = self._call_index
        self._call_index += 1
        turn = self._next_turn()

        # Simulated latency: interruptible by cancellation, and bounded by the
        # request timeout when one is set (this is how timeout is exercised
        # offline — no socket is involved).
        self._simulate_delay(turn.delay_seconds, request, cancellation)

        if turn.error_kind:
            raise ProviderError(
                turn.error_kind,
                self.provider_id,
                safe_message=turn.error_message,
            )

        response_id = f"fake_resp_{self._response_index}"
        self._response_index += 1

        tool_calls = self._build_tool_calls(turn)
        finish_reason = turn.finish_reason
        if tool_calls and finish_reason == FinishReason.STOP:
            finish_reason = FinishReason.TOOL_CALLS

        content: list[ContentPart] = [TextPart(turn.text)] if turn.text else []

        return ModelResponse(
            id=response_id,
            model=self.model,
            provider=self.provider_id,
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=turn.usage if turn.usage is not None else self._estimate_usage(request, turn),
            created_at=self._fixed_created_at,
            metadata={"provider": {self.provider_id: {"turn_index": call_index}}},
        )

    # -- Internals -----------------------------------------------------------

    def _next_turn(self) -> FakeTurn:
        if self._script:
            turn = self._script.pop(0)
            return turn
        return FakeTurn(text=self._default_text)

    def _build_tool_calls(self, turn: FakeTurn) -> list[ToolCall]:
        if not turn.tool_calls:
            return []
        # Deterministic ids: call_<n> regardless of provider-side randomness.
        raw = []
        for entry in turn.tool_calls:
            item = dict(entry)
            item.setdefault("id", f"call_{self._tool_call_index}")
            self._tool_call_index += 1
            raw.append(item)
        return normalize_tool_calls(raw, self.provider_id)

    def _estimate_usage(self, request: ModelRequest, turn: FakeTurn) -> Usage:
        prompt = request.estimated_prompt_tokens()
        completion = max(1, len(turn.text) // 4) if turn.text else 0
        return Usage(prompt_tokens=prompt, completion_tokens=completion)

    def _simulate_delay(
        self,
        delay_seconds: float,
        request: ModelRequest,
        cancellation: CancellationToken | None,
    ) -> None:
        if delay_seconds <= 0:
            return

        timeout = request.timeout_seconds
        if timeout is not None and delay_seconds > timeout:
            # Deterministic timeout: the scripted work would outlive the budget.
            raise provider_timeout_error(
                self.provider_id,
                safe_message=(
                    f"scripted delay {delay_seconds}s exceeds timeout {timeout}s"
                ),
            )

        if not self._sleep:
            return

        deadline = time.monotonic() + delay_seconds
        while True:
            if cancellation is not None:
                # ``wait`` returns True when cancelled → raise promptly.
                if cancellation.wait(min(_CANCEL_POLL_SECONDS, max(0.0, deadline - time.monotonic()))):
                    cancellation.raise_if_cancelled(self.provider_id)
            else:
                time.sleep(min(_CANCEL_POLL_SECONDS, max(0.0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                return

    # -- Convenience constructors (used by tests and LAB) --------------------

    @classmethod
    def success(
        cls, text: str = "fake response", *, model: str = "fake-model", **kwargs: Any
    ) -> FakeProvider:
        caps = kwargs.pop("capabilities", None) or ProviderCapabilities(
            chat=True, streaming=True, tool_calls=True, structured_output=True
        )
        return cls(
            model=model,
            capabilities=caps,
            script=[FakeTurn(text=text)],
            default_text=text,
            **kwargs,
        )

    @classmethod
    def with_tool_calls(
        cls,
        tool_calls: list[dict[str, Any]],
        *,
        text: str = "",
        model: str = "fake-model",
        **kwargs: Any,
    ) -> FakeProvider:
        caps = kwargs.pop("capabilities", None) or ProviderCapabilities(
            chat=True, streaming=True, tool_calls=True, structured_output=True
        )
        return cls(
            model=model,
            capabilities=caps,
            script=[FakeTurn(text=text, tool_calls=tool_calls)],
            default_text=text,
            **kwargs,
        )

    @classmethod
    def timing_out(
        cls,
        *,
        delay_seconds: float = 60.0,
        model: str = "fake-model",
        **kwargs: Any,
    ) -> FakeProvider:
        caps = kwargs.pop("capabilities", None) or ProviderCapabilities(chat=True, streaming=True)
        return cls(
            model=model,
            capabilities=caps,
            script=[FakeTurn(delay_seconds=delay_seconds)],
            **kwargs,
        )

    @classmethod
    def refusing(
        cls,
        text: str = "I cannot help with that.",
        *,
        reason: str = FinishReason.REFUSAL,
        model: str = "fake-model",
        **kwargs: Any,
    ) -> FakeProvider:
        caps = kwargs.pop("capabilities", None) or ProviderCapabilities(chat=True, streaming=True)
        return cls(
            model=model,
            capabilities=caps,
            script=[FakeTurn(text=text, finish_reason=reason)],
            default_text=text,
            **kwargs,
        )

    @classmethod
    def failing(
        cls,
        kind: str = ProviderErrorKind.UNAVAILABLE,
        *,
        message: str = "",
        model: str = "fake-model",
        **kwargs: Any,
    ) -> FakeProvider:
        caps = kwargs.pop("capabilities", None) or ProviderCapabilities(chat=True, streaming=True)
        return cls(
            model=model,
            capabilities=caps,
            script=[FakeTurn(error_kind=kind, error_message=message)],
            **kwargs,
        )


__all__ = ["FakeProvider", "FakeTurn"]
