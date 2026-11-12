# Global safety rules (S20). Always merged into every PolicySet; user, identity,
# project and skill rules cannot remove or override them, because the engine
# lets the most restrictive matching outcome win.

from __future__ import annotations

from seraphim.aegis.policy import PolicyRule, PolicySet

GLOBAL_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(
        rule_id="aegis.global.destructive_requires_confirmation",
        outcome="ASK_USER",
        source="global",
        side_effects=("destructive",),
        priority=100,
        reason="Destructive actions require your confirmation.",
        waived_when_confirmed=True,
    ),
    PolicyRule(
        rule_id="aegis.global.external_requires_confirmation",
        outcome="ASK_USER",
        source="global",
        side_effects=("external",),
        priority=100,
        reason="Actions that reach outside the local system require your confirmation.",
        waived_when_confirmed=True,
    ),
    PolicyRule(
        rule_id="aegis.global.secret_data_denied",
        outcome="DENY",
        source="global",
        data_sensitivity=("secret",),
        priority=200,
        reason="Secret data is never passed to a tool without an explicit separate grant.",
    ),
)


def build_policy_set(extra: tuple[PolicyRule, ...] = ()) -> PolicySet:
    return PolicySet(rules=(*GLOBAL_RULES, *extra))
