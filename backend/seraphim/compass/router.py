from __future__ import annotations

import fnmatch
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer.health import HealthStatus
from seraphim.model_layer.provider import ModelProvider
from seraphim.model_layer.request import ModelRequest
from seraphim.model_layer.transmission import decide_transmission
from seraphim.sanctum.config_schemas import RoutingRule
from seraphim.sanctum.privacy import PrivacyPolicy

COMPONENT = "compass.router"

_USABLE_HEALTH = frozenset({HealthStatus.ONLINE, HealthStatus.DEGRADED})


class RoutingMode(StrEnum):
    MANUAL = "manual"
    RULE_BASED = "rule_based"


@dataclass(frozen=True)
class Candidate:
    """A configured model the router may choose.

    ``external`` is ``False`` only for a loopback endpoint; ``health`` is the
    status PULSE last reported for it.  The router never probes a provider itself.
    """

    model_id: str
    provider: ModelProvider
    external: bool = True
    health: HealthStatus = HealthStatus.UNKNOWN


@dataclass(frozen=True)
class RoutingDecision:
    model_id: str
    provider_id: str
    mode: str
    reason: str
    fallback: bool
    rejected: tuple[tuple[str, str], ...] = ()
    explanation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "mode": self.mode,
            "reason": self.reason,
            "fallback": self.fallback,
            "rejected": [{"model_id": m, "reason": r} for m, r in self.rejected],
            "explanation": self.explanation,
        }


def _error(code: str, message: str, **details: Any) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        user_action_required=True,
        details=details or None,
    )


class ModelRouter:
    """Choose one candidate for a request, with an explanation for every rejection.

    The same inputs always produce the same decision: candidates are considered in
    the order given, rules in ``(-priority, id)`` order, and the first passing
    candidate wins.
    """

    def __init__(
        self,
        candidates: Sequence[Candidate],
        *,
        privacy_policy: PrivacyPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.model_id in seen:
                raise _error(
                    ErrorCode.COMPASS_CONFLICT,
                    f"model {candidate.model_id!r} is configured more than once",
                )
            seen.add(candidate.model_id)
        self._candidates: dict[str, Candidate] = {c.model_id: c for c in candidates}
        self._order: tuple[str, ...] = tuple(c.model_id for c in candidates)
        self._privacy_policy = privacy_policy
        self._clock = clock

    def route(
        self,
        request: ModelRequest,
        *,
        mode: RoutingMode | str = RoutingMode.RULE_BASED,
        task: str = "",
        model_id: str = "",
        rules: Sequence[RoutingRule] = (),
        offline: bool = False,
        timeout_seconds: float | None = None,
    ) -> RoutingDecision:
        mode = RoutingMode(mode)
        started = self._clock()
        rejected: list[tuple[str, str]] = []

        def check_deadline() -> None:
            if timeout_seconds is not None and self._clock() - started > timeout_seconds:
                raise _error(
                    ErrorCode.ROUTING_TIMEOUT,
                    f"routing exceeded {timeout_seconds}s",
                )

        if mode is RoutingMode.MANUAL:
            if not model_id:
                raise _error(ErrorCode.VALIDATION_FAILED, "manual routing needs a model_id")
            candidate = self._candidates.get(model_id)
            if candidate is None:
                raise _error(
                    ErrorCode.NO_MODEL_AVAILABLE,
                    f"model {model_id!r} is not configured",
                    model_id=model_id,
                )
            check_deadline()
            reason = self._rejection(candidate, request, offline)
            if reason is not None:
                raise _error(
                    ErrorCode.COMPASS_CONFLICT,
                    f"requested model {model_id!r} cannot serve this request: {reason}",
                    model_id=model_id,
                    reason=reason,
                )
            return self._decision(
                candidate, mode, "manual: model requested explicitly", False, rejected, request
            )

        for rule in sorted(rules, key=lambda r: (-r.priority, r.id)):
            check_deadline()
            if not fnmatch.fnmatchcase(task, rule.pattern):
                continue
            candidate = self._candidates.get(rule.model_id)
            if candidate is None:
                rejected.append((rule.model_id, f"rule {rule.id!r}: model not configured"))
                continue
            reason = self._rejection(candidate, request, offline)
            if reason is None:
                return self._decision(
                    candidate, mode, f"rule:{rule.id}", False, rejected, request
                )
            rejected.append((candidate.model_id, f"rule {rule.id!r}: {reason}"))

        for model_id_in_order in self._order:
            check_deadline()
            candidate = self._candidates[model_id_in_order]
            reason = self._rejection(candidate, request, offline)
            if reason is None:
                return self._decision(
                    candidate,
                    mode,
                    "fallback: first usable candidate in declared order",
                    True,
                    rejected,
                    request,
                )
            rejected.append((candidate.model_id, reason))

        raise _error(
            ErrorCode.NO_MODEL_AVAILABLE,
            "no configured model can serve this request",
            rejected=[{"model_id": m, "reason": r} for m, r in rejected],
        )

    def _rejection(self, candidate: Candidate, request: ModelRequest, offline: bool) -> str | None:
        if offline and candidate.external:
            return "offline mode allows only local models"
        if candidate.health not in _USABLE_HEALTH:
            return f"health is {candidate.health.value}, not usable"

        caps = candidate.provider.verified_capabilities()
        declared = candidate.provider.get_capabilities()
        needed = []
        if request.tools:
            needed.append(("tool_calls", caps.tool_calls))
        if request.has_images():
            needed.append(("vision", caps.vision))
        if request.response_schema is not None:
            needed.append(("structured_output", caps.structured_output))
        if request.stream:
            needed.append(("streaming", caps.streaming))
        for feature, supported in needed:
            if not supported:
                return f"feature {feature!r} is not verified for this model"

        if declared.context_limit and request.estimated_prompt_tokens() > declared.context_limit:
            return (
                f"prompt needs about {request.estimated_prompt_tokens()} tokens, "
                f"context limit is {declared.context_limit}"
            )
        if declared.max_images and len(request.images()) > declared.max_images:
            return f"request has more images than the limit of {declared.max_images}"

        decision = decide_transmission(
            self._privacy_policy,
            candidate.provider.provider_id,
            request,
            model=candidate.model_id,
            purpose="chat",
            external=candidate.external,
        )
        if not decision.allowed:
            return f"privacy policy: {decision.reason}"
        return None

    def _decision(
        self,
        candidate: Candidate,
        mode: RoutingMode,
        reason: str,
        fallback: bool,
        rejected: list[tuple[str, str]],
        request: ModelRequest,
    ) -> RoutingDecision:
        explanation = reason
        if rejected:
            explanation += "; rejected: " + ", ".join(f"{m} ({r})" for m, r in rejected)
        return RoutingDecision(
            model_id=candidate.model_id,
            provider_id=candidate.provider.provider_id,
            mode=str(mode),
            reason=reason,
            fallback=fallback,
            rejected=tuple(rejected),
            explanation=explanation,
            metadata={"external": candidate.external, "stream": request.stream},
        )


__all__ = [
    "Candidate",
    "ModelRouter",
    "RoutingDecision",
    "RoutingMode",
]
