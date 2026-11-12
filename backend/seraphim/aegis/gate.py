# AEGIS gate for WINGS (S20): turns a ToolManifest + ToolCall into a PolicyRequest and
# a decision. Lives in AEGIS so WINGS only sees the PolicyGate callable and never imports
# the engine's rule types. Any failure to evaluate is a DENY, never an allow or a crash.

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from seraphim.aegis.policy import PolicyDecision, PolicyEngine, PolicyRequest

GATE_FAILED_RULE = "aegis.gate.evaluation_failed"


def _never_confirmed(call: Any) -> bool:
    return False


def make_gate(
    engine: PolicyEngine,
    *,
    actor: str,
    execution_context: str = "interactive",
    data_sensitivity: str = "internal",
    confirmed: Callable[[Any], bool] = _never_confirmed,
) -> Any:
    def gate(manifest: Any, call: Any) -> PolicyDecision:
        try:
            request = PolicyRequest(
                actor=actor,
                component=f"wings.{manifest.source}",
                tool_id=call.tool_id,
                action=manifest.side_effects,
                side_effects=manifest.side_effects,
                risk=manifest.risk,
                data_sensitivity=data_sensitivity,
                execution_context=execution_context,
                domain=manifest.capabilities[0].split(".")[0],
                permissions=tuple(manifest.permissions),
                user_confirmed=bool(confirmed(call)),
            )
            return engine.decide(request)
        except Exception:
            return PolicyDecision(
                outcome="DENY",
                reason="Policy could not be evaluated for this call.",
                rule_id=GATE_FAILED_RULE,
            )

    return gate
