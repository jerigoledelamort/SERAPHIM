# AEGIS policy engine (S20): independent ALLOW/DENY/ASK_USER/ALLOW_WITH_LIMITS decisions.
# Pure logic: no I/O, no task DB, no UI. Rules are supplied by the caller; the engine
# never loads them from files and never widens them. Where rule storage lives is
# ADR-015 (PROPOSED) and is intentionally not decided here.
#
# Combination model: every matching rule votes; the most restrictive outcome wins
# (DENY > ASK_USER > ALLOW_WITH_LIMITS > ALLOW). A lower-authority rule can therefore
# never override a higher-authority restriction. No match means DENY.

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from seraphim.contracts.constants import RISK_LEVELS, SIDE_EFFECTS
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.permissions import validate_permission

COMPONENT = "aegis.policy"

OUTCOMES: tuple[str, ...] = ("ALLOW", "DENY", "ASK_USER", "ALLOW_WITH_LIMITS")
DATA_SENSITIVITY: tuple[str, ...] = ("public", "internal", "personal", "secret")
EXECUTION_CONTEXTS: tuple[str, ...] = ("interactive", "background", "sandbox")
SOURCES: tuple[str, ...] = ("global", "identity", "project", "user", "skill")

GLOBAL_RULE_PREFIX = "aegis.global."
DEFAULT_DENY_RULE = "aegis.default.deny"
INVALID_REQUEST_RULE = "aegis.request.invalid"

_RESTRICTIVENESS = {"ALLOW": 0, "ALLOW_WITH_LIMITS": 1, "ASK_USER": 2, "DENY": 3}
_GRANTING_OUTCOMES = frozenset({"ALLOW", "ALLOW_WITH_LIMITS"})
_GRANTING_SOURCES = frozenset({"global", "user"})
_MAX_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class PolicyRequest:
    actor: str
    component: str
    tool_id: str
    action: str
    side_effects: str
    risk: str
    data_sensitivity: str
    execution_context: str
    resource: str = ""
    path: str = ""
    domain: str = ""
    permissions: tuple[str, ...] = ()
    user_confirmed: bool = False

    def __post_init__(self) -> None:
        for name in ("actor", "component", "tool_id", "action"):
            if not getattr(self, name):
                raise _invalid(f"Policy request field {name} is required")
        _check_choice("side_effects", self.side_effects, SIDE_EFFECTS)
        _check_choice("risk", self.risk, RISK_LEVELS)
        _check_choice("data_sensitivity", self.data_sensitivity, DATA_SENSITIVITY)
        _check_choice("execution_context", self.execution_context, EXECUTION_CONTEXTS)
        for perm in self.permissions:
            validate_permission(perm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "component": self.component,
            "tool_id": self.tool_id,
            "action": self.action,
            "side_effects": self.side_effects,
            "risk": self.risk,
            "data_sensitivity": self.data_sensitivity,
            "execution_context": self.execution_context,
            "resource": self.resource,
            "path": self.path,
            "domain": self.domain,
            "permissions": list(self.permissions),
        }


@dataclass(frozen=True)
class PolicyLimits:
    timeout_seconds: int | None = None
    allowed_roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and not 1 <= self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise _invalid(f"timeout_seconds must be 1..{_MAX_TIMEOUT_SECONDS}")


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    outcome: str
    source: str
    tool_pattern: str = "*"
    side_effects: tuple[str, ...] = ()
    max_risk: str = "critical"
    data_sensitivity: tuple[str, ...] = ()
    execution_contexts: tuple[str, ...] = ()
    limits: PolicyLimits | None = None
    priority: int = 0
    reason: str = ""
    waived_when_confirmed: bool = False

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise _invalid("Policy rule needs an id")
        if self.waived_when_confirmed and (self.outcome != "ASK_USER" or self.source != "global"):
            raise _invalid(f"Rule {self.rule_id}: only global ASK_USER rules can be waived by confirmation")
        _check_choice(f"{self.rule_id} outcome", self.outcome, OUTCOMES)
        _check_choice(f"{self.rule_id} source", self.source, SOURCES)
        _check_choice(f"{self.rule_id} max_risk", self.max_risk, RISK_LEVELS)
        for se in self.side_effects:
            _check_choice(f"{self.rule_id} side_effects", se, SIDE_EFFECTS)
        for ds in self.data_sensitivity:
            _check_choice(f"{self.rule_id} data_sensitivity", ds, DATA_SENSITIVITY)
        for ctx in self.execution_contexts:
            _check_choice(f"{self.rule_id} execution_context", ctx, EXECUTION_CONTEXTS)
        if (self.source == "global") != self.rule_id.startswith(GLOBAL_RULE_PREFIX):
            raise _invalid(f"Rule {self.rule_id}: global rules and only global rules use the aegis.global. prefix")
        if (self.outcome == "ALLOW_WITH_LIMITS") != (self.limits is not None):
            raise _invalid(f"Rule {self.rule_id}: limits are required exactly for ALLOW_WITH_LIMITS")
        if self.outcome in _GRANTING_OUTCOMES and self.source not in _GRANTING_SOURCES:
            raise _invalid(
                f"Rule {self.rule_id}: source {self.source} can only restrict; "
                "granting rights requires global or user policy"
            )

    def matches(self, request: PolicyRequest) -> bool:
        if self.waived_when_confirmed and request.user_confirmed:
            return False
        if not _tool_matches(self.tool_pattern, request.tool_id):
            return False
        if self.side_effects and request.side_effects not in self.side_effects:
            return False
        if RISK_LEVELS.index(request.risk) > RISK_LEVELS.index(self.max_risk):
            return False
        if self.data_sensitivity and request.data_sensitivity not in self.data_sensitivity:
            return False
        return not (self.execution_contexts and request.execution_context not in self.execution_contexts)


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str
    reason: str
    rule_id: str
    limits: PolicyLimits | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome in ("ALLOW", "ALLOW_WITH_LIMITS")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"outcome": self.outcome, "reason": self.reason, "rule_id": self.rule_id}
        if self.limits is not None:
            data["limits"] = {
                "timeout_seconds": self.limits.timeout_seconds,
                "allowed_roots": list(self.limits.allowed_roots),
            }
        return data


@dataclass(frozen=True)
class PolicySet:
    rules: tuple[PolicyRule, ...] = field(default=())

    def __post_init__(self) -> None:
        ids = [r.rule_id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise _invalid("Policy rule ids must be unique")


class PolicyEngine:
    """Decides each request independently. No matching rule means DENY."""

    def __init__(self, policy_set: PolicySet | None = None) -> None:
        rules = (policy_set or PolicySet()).rules
        self._rules = MappingProxyType({r.rule_id: r for r in rules})

    def decide(self, request: object) -> PolicyDecision:
        if not isinstance(request, PolicyRequest):
            return _deny("Policy request is malformed.", INVALID_REQUEST_RULE)
        try:
            matched = [r for r in self._rules.values() if r.matches(request)]
        except Exception:
            return _deny("Policy evaluation failed.", DEFAULT_DENY_RULE)
        if not matched:
            return _deny("No policy rule allows this action.", DEFAULT_DENY_RULE)
        winner = max(matched, key=lambda r: (_RESTRICTIVENESS[r.outcome], r.priority, r.rule_id))
        return PolicyDecision(
            outcome=winner.outcome,
            reason=winner.reason or _default_reason(winner.outcome),
            rule_id=winner.rule_id,
            limits=winner.limits,
        )

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rules))


def _tool_matches(pattern: str, tool_id: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return tool_id.startswith(pattern[:-1])
    return pattern == tool_id


def _check_choice(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise _invalid(f"Unknown {name} {value!r}")


def _default_reason(outcome: str) -> str:
    return {
        "ALLOW": "Allowed by policy.",
        "DENY": "Denied by policy.",
        "ASK_USER": "Requires your confirmation.",
        "ALLOW_WITH_LIMITS": "Allowed with limits.",
    }[outcome]


def _deny(reason: str, rule_id: str) -> PolicyDecision:
    return PolicyDecision(outcome="DENY", reason=reason, rule_id=rule_id)


def _invalid(message: str) -> SeraphimError:
    return SeraphimError(code=ErrorCode.POLICY_EVALUATION_FAILED, component=COMPONENT, safe_message=message)
