# AEGIS policy engine (S20). Offline: pure decisions, no tools executed.

from __future__ import annotations

import pytest
from seraphim.aegis import (
    GLOBAL_RULES,
    PolicyDecision,
    PolicyEngine,
    PolicyLimits,
    PolicyRequest,
    PolicyRule,
    PolicySet,
    build_policy_set,
)
from seraphim.contracts.errors import ErrorCode, SeraphimError


def _request(**overrides: object) -> PolicyRequest:
    base: dict[str, object] = {
        "actor": "agent_main",
        "component": "core.executor",
        "tool_id": "tool.fs.read_file",
        "action": "read",
        "side_effects": "read",
        "risk": "low",
        "data_sensitivity": "internal",
        "execution_context": "interactive",
        "path": "project/readme.md",
        "permissions": ("filesystem.read",),
    }
    base.update(overrides)
    return PolicyRequest(**base)  # type: ignore[arg-type]


def _allow_user(tool_pattern: str = "tool.fs.*", **kwargs: object) -> PolicyRule:
    return PolicyRule(
        rule_id=f"aegis.user.allow.{tool_pattern.replace('*', 'all').replace('.', '_')}",
        outcome="ALLOW",
        source="user",
        tool_pattern=tool_pattern,
        **kwargs,  # type: ignore[arg-type]
    )


class TestRequestContext:
    def test_request_carries_full_context(self) -> None:
        data = _request(resource="readme", domain="filesystem").to_dict()
        for key in (
            "actor",
            "component",
            "tool_id",
            "action",
            "side_effects",
            "risk",
            "data_sensitivity",
            "execution_context",
            "path",
            "permissions",
        ):
            assert key in data

    @pytest.mark.parametrize(
        "field,value",
        [
            ("side_effects", "rm"),
            ("risk", "extreme"),
            ("data_sensitivity", "top"),
            ("execution_context", "cloud"),
        ],
    )
    def test_unknown_enum_value_is_rejected_at_construction(self, field: str, value: str) -> None:
        with pytest.raises(SeraphimError) as exc:
            _request(**{field: value})
        assert exc.value.code == ErrorCode.POLICY_EVALUATION_FAILED

    def test_missing_actor_is_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            _request(actor="")

    def test_invalid_permission_string_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _request(permissions=("Filesystem Read",))


class TestDefaultDeny:
    def test_empty_policy_set_denies_everything(self) -> None:
        decision = PolicyEngine().decide(_request())
        assert decision.outcome == "DENY"
        assert not decision.allowed
        assert decision.rule_id == "aegis.default.deny"

    def test_missing_rule_for_unknown_tool_is_denied(self) -> None:
        engine = PolicyEngine(PolicySet(rules=(_allow_user("tool.fs.read_file"),)))
        decision = engine.decide(_request(tool_id="tool.shell.run"))
        assert decision.outcome == "DENY"
        assert decision.rule_id == "aegis.default.deny"

    def test_unknown_tool_is_denied_even_with_wildcard_on_other_namespace(self) -> None:
        engine = PolicyEngine(PolicySet(rules=(_allow_user("tool.fs.*"),)))
        assert engine.decide(_request(tool_id="tool.mcp.evil")).outcome == "DENY"

    def test_malformed_request_object_is_denied(self) -> None:
        decision = PolicyEngine().decide({"tool_id": "tool.fs.read_file"})  # type: ignore[arg-type]
        assert decision.outcome == "DENY"
        assert decision.rule_id == "aegis.request.invalid"

    def test_denial_reason_is_safe_and_explanatory(self) -> None:
        decision = PolicyEngine().decide(_request())
        assert decision.reason
        assert "token" not in decision.reason.lower()
        assert "traceback" not in decision.reason.lower()


class TestAllowAndLimits:
    def test_explicit_user_allow_is_allowed(self) -> None:
        engine = PolicyEngine(PolicySet(rules=(_allow_user(),)))
        decision = engine.decide(_request())
        assert decision.outcome == "ALLOW"
        assert decision.allowed
        assert decision.rule_id.startswith("aegis.user.")

    def test_allow_with_limits_carries_limits(self) -> None:
        rule = PolicyRule(
            rule_id="aegis.user.limited",
            outcome="ALLOW_WITH_LIMITS",
            source="user",
            tool_pattern="tool.fs.read_file",
            limits=PolicyLimits(timeout_seconds=10, allowed_roots=("project",)),
        )
        decision = PolicyEngine(PolicySet(rules=(rule,))).decide(_request())
        assert decision.outcome == "ALLOW_WITH_LIMITS"
        assert decision.allowed
        assert decision.limits is not None and decision.limits.timeout_seconds == 10
        assert decision.to_dict()["limits"]["allowed_roots"] == ["project"]

    def test_limits_required_for_allow_with_limits(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="aegis.user.bad", outcome="ALLOW_WITH_LIMITS", source="user")

    def test_limits_forbidden_for_plain_allow(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="aegis.user.bad", outcome="ALLOW", source="user", limits=PolicyLimits(5))

    def test_timeout_limit_bounds(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyLimits(timeout_seconds=0)
        with pytest.raises(SeraphimError):
            PolicyLimits(timeout_seconds=601)


class TestAskUser:
    def test_destructive_action_requires_confirmation(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow_user(side_effects=("destructive",)),)))
        decision = engine.decide(
            _request(tool_id="tool.fs.delete_file", side_effects="destructive", risk="high", action="delete")
        )
        assert decision.outcome == "ASK_USER"
        assert not decision.allowed
        assert decision.rule_id == "aegis.global.destructive_requires_confirmation"

    def test_external_network_requires_confirmation(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow_user(side_effects=("external",)),)))
        decision = engine.decide(
            _request(tool_id="tool.net.http_get", side_effects="external", risk="medium", action="fetch")
        )
        assert decision.outcome == "ASK_USER"
        assert decision.rule_id == "aegis.global.external_requires_confirmation"


class TestPriorityConflicts:
    def test_user_allow_cannot_override_global_ask_for_destructive(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow_user(side_effects=("destructive",)),)))
        decision = engine.decide(_request(tool_id="tool.fs.wipe", side_effects="destructive", risk="high"))
        assert decision.outcome != "ALLOW"

    def test_skill_allow_cannot_grant_access(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="skill.freecad.allow", outcome="ALLOW", source="skill")

    def test_skill_restriction_is_accepted(self) -> None:
        skill_deny = PolicyRule(rule_id="skill.fs.deny", outcome="DENY", source="skill", tool_pattern="tool.fs.*")
        engine = PolicyEngine(PolicySet(rules=(_allow_user(), skill_deny)))
        assert engine.decide(_request()).outcome == "DENY"

    def test_identity_cannot_grant_access(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="identity.persona.allow", outcome="ALLOW", source="identity")

    def test_project_cannot_grant_access(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="project.repo.allow", outcome="ALLOW_WITH_LIMITS", source="project", limits=PolicyLimits(5))

    def test_most_restrictive_outcome_wins_over_priority(self) -> None:
        low_allow = _allow_user(priority=999)
        high_deny = PolicyRule(
            rule_id="aegis.user.deny", outcome="DENY", source="user", tool_pattern="tool.fs.read_file", priority=0
        )
        decision = PolicyEngine(PolicySet(rules=(low_allow, high_deny))).decide(_request())
        assert decision.outcome == "DENY"
        assert decision.rule_id == "aegis.user.deny"

    def test_same_outcome_tie_is_resolved_by_priority(self) -> None:
        ask_low = PolicyRule(rule_id="aegis.user.ask_low", outcome="ASK_USER", source="user", priority=1)
        ask_high = PolicyRule(rule_id="aegis.user.ask_high", outcome="ASK_USER", source="user", priority=5)
        decision = PolicyEngine(PolicySet(rules=(ask_low, ask_high))).decide(_request())
        assert decision.rule_id == "aegis.user.ask_high"

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            PolicySet(rules=(_allow_user("tool.fs.read_file"), _allow_user("tool.fs.read_file")))


class TestImmutableGlobal:
    def test_user_rule_cannot_use_global_prefix(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="aegis.global.hole", outcome="ALLOW", source="user")

    def test_global_rule_must_use_global_prefix(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="aegis.custom.hole", outcome="ALLOW", source="global")

    def test_global_rules_are_present_in_every_built_set(self) -> None:
        ids = PolicyEngine(build_policy_set()).rule_ids()
        for rule in GLOBAL_RULES:
            assert rule.rule_id in ids

    def test_global_secret_deny_wins_over_user_allow(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow_user(),)))
        decision = engine.decide(_request(data_sensitivity="secret"))
        assert decision.outcome == "DENY"
        assert decision.rule_id == "aegis.global.secret_data_denied"

    def test_global_rules_cannot_be_removed_by_passing_empty_extra(self) -> None:
        engine = PolicyEngine(build_policy_set(()))
        assert engine.decide(_request(tool_id="tool.fs.delete", side_effects="destructive", risk="high")).outcome == "ASK_USER"


class TestTraversalAndSensitiveData:
    def test_path_text_alone_does_not_change_the_decision(self) -> None:
        engine = PolicyEngine(PolicySet(rules=(_allow_user("tool.fs.read_file"),)))
        decision = engine.decide(_request(path="../../etc/passwd"))
        assert decision.outcome == "ALLOW"
        assert decision.rule_id.startswith("aegis.user.")

    def test_secret_path_request_is_denied_by_data_sensitivity(self) -> None:
        engine = PolicyEngine(build_policy_set((_allow_user("tool.fs.read_file"),)))
        decision = engine.decide(_request(path=".env", data_sensitivity="secret"))
        assert decision.outcome == "DENY"


class TestDecisionShape:
    def test_decision_dict_has_outcome_reason_rule(self) -> None:
        data = PolicyEngine().decide(_request()).to_dict()
        assert set(data) >= {"outcome", "reason", "rule_id"}

    def test_invalid_outcome_cannot_be_constructed(self) -> None:
        with pytest.raises(SeraphimError):
            PolicyRule(rule_id="aegis.user.x", outcome="MAYBE", source="user")

    def test_decision_allowed_is_false_for_ask_user(self) -> None:
        assert PolicyDecision(outcome="ASK_USER", reason="r", rule_id="x").allowed is False
