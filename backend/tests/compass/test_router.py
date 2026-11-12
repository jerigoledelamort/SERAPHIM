# COMPASS routing tests (S15).  Offline: every provider is a FakeProvider.

from __future__ import annotations

import pytest
from seraphim.compass import Candidate, ModelRouter, RoutingMode
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer import FakeProvider, ModelRequest, ProviderCapabilities, ToolSpec
from seraphim.model_layer.content import Message
from seraphim.model_layer.health import HealthStatus
from seraphim.sanctum.config_schemas import RoutingRule
from seraphim.sanctum.privacy import PrivacyPolicy


def _request(**overrides) -> ModelRequest:
    return ModelRequest(messages=[Message.user("hello")], **overrides)


def _provider(provider_id: str, *, model: str, **caps) -> FakeProvider:
    capabilities = ProviderCapabilities(chat=True, **caps)
    return FakeProvider(provider_id, model, capabilities=capabilities)


def _candidate(model_id: str, *, external: bool = False, health=HealthStatus.ONLINE, **caps):
    return Candidate(
        model_id=model_id,
        provider=_provider(f"p-{model_id}", model=model_id, **caps),
        external=external,
        health=health,
    )


OPEN_POLICY = PrivacyPolicy(
    allow_external_transmission=True,
    allowed_providers=frozenset({"p-cloud", "p-local", "p-a", "p-b"}),
)


class TestManualRouting:
    def test_explains_explicit_choice(self):
        router = ModelRouter([_candidate("local-a")])
        decision = router.route(_request(), mode=RoutingMode.MANUAL, model_id="local-a")
        assert decision.model_id == "local-a"
        assert decision.mode == "manual"
        assert decision.fallback is False
        assert "requested explicitly" in decision.explanation

    def test_unknown_model_is_no_model_available(self):
        router = ModelRouter([_candidate("local-a")])
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(), mode=RoutingMode.MANUAL, model_id="missing")
        assert exc.value.code == ErrorCode.NO_MODEL_AVAILABLE

    def test_incapable_requested_model_is_conflict_not_silent_fallback(self):
        router = ModelRouter([_candidate("local-a"), _candidate("local-b", structured_output=True)])
        with pytest.raises(SeraphimError) as exc:
            router.route(
                _request(response_schema={"type": "object"}),
                mode=RoutingMode.MANUAL,
                model_id="local-a",
            )
        assert exc.value.code == ErrorCode.COMPASS_CONFLICT

    def test_manual_mode_requires_model_id(self):
        router = ModelRouter([_candidate("local-a")])
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(), mode=RoutingMode.MANUAL)
        assert exc.value.code == ErrorCode.VALIDATION_FAILED


class TestRuleBasedRouting:
    def test_rule_selects_model_and_names_the_rule(self):
        router = ModelRouter([_candidate("local-a"), _candidate("local-b")])
        rules = [RoutingRule(id="code", pattern="code*", model_id="local-b")]
        decision = router.route(
            _request(), mode=RoutingMode.RULE_BASED, task="code-review", rules=rules
        )
        assert decision.model_id == "local-b"
        assert decision.reason == "rule:code"
        assert decision.fallback is False

    def test_routing_is_deterministic(self):
        router = ModelRouter([_candidate("local-a"), _candidate("local-b")])
        rules = [
            RoutingRule(id="b", pattern="*", model_id="local-b", priority=1),
            RoutingRule(id="a", pattern="*", model_id="local-a", priority=1),
        ]
        first = router.route(_request(), task="x", rules=rules)
        second = router.route(_request(), task="x", rules=rules)
        assert first == second
        assert first.model_id == "local-a"

    def test_higher_priority_rule_wins(self):
        router = ModelRouter([_candidate("local-a"), _candidate("local-b")])
        rules = [
            RoutingRule(id="low", pattern="*", model_id="local-a", priority=0),
            RoutingRule(id="high", pattern="*", model_id="local-b", priority=5),
        ]
        decision = router.route(_request(), task="x", rules=rules)
        assert decision.model_id == "local-b"

    def test_rule_skips_unusable_model_and_records_why(self):
        router = ModelRouter(
            [_candidate("local-a", health=HealthStatus.OFFLINE), _candidate("local-b")]
        )
        rules = [RoutingRule(id="r", pattern="*", model_id="local-a")]
        decision = router.route(_request(), task="x", rules=rules)
        assert decision.model_id == "local-b"
        assert any(m == "local-a" and "health" in r for m, r in decision.rejected)


class TestFallbackAndAvailability:
    def test_fallback_is_explicit_and_first_usable_in_order(self):
        router = ModelRouter(
            [_candidate("local-a", health=HealthStatus.OFFLINE), _candidate("local-b")]
        )
        decision = router.route(_request())
        assert decision.model_id == "local-b"
        assert decision.fallback is True
        assert decision.reason.startswith("fallback:")

    def test_no_model_available_lists_every_rejection(self):
        router = ModelRouter([_candidate("local-a", health=HealthStatus.OFFLINE)])
        with pytest.raises(SeraphimError) as exc:
            router.route(_request())
        assert exc.value.code == ErrorCode.NO_MODEL_AVAILABLE
        assert exc.value.sanitized_details["rejected"][0]["model_id"] == "local-a"

    def test_unknown_health_is_not_usable(self):
        router = ModelRouter([_candidate("local-a", health=HealthStatus.UNKNOWN)])
        with pytest.raises(SeraphimError) as exc:
            router.route(_request())
        assert exc.value.code == ErrorCode.NO_MODEL_AVAILABLE

    def test_routing_timeout_is_reported(self):
        ticks = iter([0.0, 0.0, 10.0])
        router = ModelRouter(
            [_candidate("local-a", health=HealthStatus.OFFLINE), _candidate("local-b")],
            clock=lambda: next(ticks),
        )
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(), timeout_seconds=1.0)
        assert exc.value.code == ErrorCode.ROUTING_TIMEOUT


class TestCapabilityFilter:
    def test_tool_request_skips_model_without_verified_tools(self):
        router = ModelRouter([_candidate("local-a"), _candidate("local-b", tool_calls=True)])
        request = _request(tools=[ToolSpec(name="t", description="d", parameters={})])
        decision = router.route(request)
        assert decision.model_id == "local-b"
        assert any(m == "local-a" for m, _ in decision.rejected)

    def test_no_model_with_required_feature_is_no_model_available(self):
        router = ModelRouter([_candidate("local-a")])
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(response_schema={"type": "object"}))
        assert exc.value.code == ErrorCode.NO_MODEL_AVAILABLE


class TestPrivacyAndOffline:
    def test_privacy_denied_external_model_is_not_selected(self):
        router = ModelRouter(
            [_candidate("cloud", external=True), _candidate("local", external=False)],
            privacy_policy=PrivacyPolicy(),
        )
        decision = router.route(_request())
        assert decision.model_id == "local"
        assert any(m == "cloud" and "privacy" in r for m, r in decision.rejected)

    def test_privacy_denied_manual_request_is_conflict(self):
        router = ModelRouter(
            [_candidate("cloud", external=True)], privacy_policy=PrivacyPolicy()
        )
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(), mode=RoutingMode.MANUAL, model_id="cloud")
        assert exc.value.code == ErrorCode.COMPASS_CONFLICT

    def test_open_policy_allows_external_model(self):
        router = ModelRouter(
            [_candidate("cloud", external=True)], privacy_policy=OPEN_POLICY
        )
        decision = router.route(_request())
        assert decision.model_id == "cloud"

    def test_offline_mode_excludes_external_models(self):
        router = ModelRouter(
            [_candidate("cloud", external=True), _candidate("local", external=False)],
            privacy_policy=OPEN_POLICY,
        )
        decision = router.route(_request(), offline=True)
        assert decision.model_id == "local"

    def test_offline_with_only_external_models_is_no_model_available(self):
        router = ModelRouter(
            [_candidate("cloud", external=True)], privacy_policy=OPEN_POLICY
        )
        with pytest.raises(SeraphimError) as exc:
            router.route(_request(), offline=True)
        assert exc.value.code == ErrorCode.NO_MODEL_AVAILABLE


class TestConfiguration:
    def test_duplicate_model_id_is_conflict(self):
        with pytest.raises(SeraphimError) as exc:
            ModelRouter([_candidate("local-a"), _candidate("local-a")])
        assert exc.value.code == ErrorCode.COMPASS_CONFLICT

    def test_decision_serializes_without_provider_objects(self):
        router = ModelRouter([_candidate("local-a")])
        data = router.route(_request()).to_dict()
        assert data["model_id"] == "local-a"
        assert isinstance(data["rejected"], list)
