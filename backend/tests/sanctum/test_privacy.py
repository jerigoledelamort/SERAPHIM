# SERAPHIM SANCTUM — privacy gate tests (S09).
#
# Acceptance: the privacy policy is checked before any context leaves the
# machine, the user is shown what would be sent, and nothing is uploaded
# silently.  TB-9: user data → outward is a policy + user decision.

from __future__ import annotations

import json

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum.config_schemas import PrivacyConfig
from seraphim.sanctum.privacy import (
    DATA_CATEGORIES,
    REASON_ALLOWED,
    REASON_EXTERNAL_DISABLED,
    REASON_LOCAL_ONLY,
    REASON_LOCAL_PROVIDER,
    REASON_PROVIDER_NOT_ALLOWED,
    PrivacyPolicy,
    TransmissionRequest,
    assert_transmission_allowed,
    evaluate_transmission,
    prepare_payload,
    render_summary,
    summarize_request,
)

MARKER_SECRET = "SERAPHIM_TEST_SECRET_xyz789"


def _open_policy(**overrides) -> PrivacyPolicy:
    defaults = {
        "allow_external_transmission": True,
        "allowed_providers": frozenset({"openai"}),
        "require_confirmation": True,
    }
    defaults.update(overrides)
    return PrivacyPolicy(**defaults)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_lists_provider_and_categories(self) -> None:
        request = TransmissionRequest("openai", ("prompt", "files"), model="gpt-4o")
        summary = summarize_request(request)
        assert summary["provider"] == "openai"
        assert summary["model"] == "gpt-4o"
        assert summary["destination"] == "external"
        assert [c["id"] for c in summary["data_categories"]] == ["prompt", "files"]
        assert summary["total_categories"] == 2

    def test_summary_contains_no_payload(self) -> None:
        request = TransmissionRequest("openai", ("prompt",))
        summary = summarize_request(request)
        # The summary is a fixed whitelist of metadata: there is no field a
        # payload could travel in, and category entries carry only an id plus a
        # static description.
        assert set(summary) == {
            "provider",
            "model",
            "purpose",
            "destination",
            "data_categories",
            "total_categories",
        }
        assert all(set(category) == {"id", "description"} for category in summary["data_categories"])
        assert MARKER_SECRET not in json.dumps(summary)
        assert "data_categories" in summary

    def test_render_summary_is_human_readable(self) -> None:
        text = render_summary(summarize_request(TransmissionRequest("openai", ("prompt",))))
        assert "Privacy summary" in text
        assert "openai" in text
        assert "prompt" in text

    def test_local_destination_reported(self) -> None:
        summary = summarize_request(
            TransmissionRequest("ollama", ("prompt",), external=False)
        )
        assert summary["destination"] == "local"

    def test_all_documented_categories_are_described(self) -> None:
        for category, description in DATA_CATEGORIES.items():
            assert description
            assert summarize_request(TransmissionRequest("openai", (category,)))


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class TestRequestValidation:
    def test_provider_required(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            TransmissionRequest("", ("prompt",))
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_unknown_category_rejected(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            TransmissionRequest("openai", ("prompt", "soul"))
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert "soul" in exc.value.safe_message


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class TestDecision:
    def test_default_policy_denies_external_transmission(self) -> None:
        decision = evaluate_transmission(
            PrivacyPolicy(), TransmissionRequest("openai", ("prompt",))
        )
        assert decision.allowed is False
        assert decision.reason == REASON_EXTERNAL_DISABLED

    def test_local_only_denies_even_when_external_is_enabled(self) -> None:
        decision = evaluate_transmission(
            _open_policy(local_only=True), TransmissionRequest("openai", ("prompt",))
        )
        assert decision.allowed is False
        assert decision.reason == REASON_LOCAL_ONLY

    def test_provider_outside_allow_list_denied(self) -> None:
        decision = evaluate_transmission(
            _open_policy(), TransmissionRequest("anthropic", ("prompt",))
        )
        assert decision.allowed is False
        assert decision.reason == REASON_PROVIDER_NOT_ALLOWED

    def test_allowed_provider_passes_with_confirmation(self) -> None:
        decision = evaluate_transmission(
            _open_policy(), TransmissionRequest("openai", ("prompt",))
        )
        assert decision.allowed is True
        assert decision.reason == REASON_ALLOWED
        assert decision.requires_confirmation is True

    def test_confirmation_can_be_disabled_by_policy(self) -> None:
        decision = evaluate_transmission(
            _open_policy(require_confirmation=False),
            TransmissionRequest("openai", ("prompt",)),
        )
        assert decision.allowed is True
        assert decision.requires_confirmation is False

    def test_local_provider_allowed_without_policy_opt_in(self) -> None:
        decision = evaluate_transmission(
            PrivacyPolicy(), TransmissionRequest("ollama", ("prompt",), external=False)
        )
        assert decision.allowed is True
        assert decision.reason == REASON_LOCAL_PROVIDER
        assert decision.requires_confirmation is False

    def test_decision_is_deterministic(self) -> None:
        policy = _open_policy()
        request = TransmissionRequest("openai", ("prompt", "files"))
        first = evaluate_transmission(policy, request)
        second = evaluate_transmission(policy, request)
        assert first.to_dict() == second.to_dict()

    def test_decision_carries_summary(self) -> None:
        decision = evaluate_transmission(
            _open_policy(), TransmissionRequest("openai", ("files",))
        )
        assert decision.summary["provider"] == "openai"
        assert decision.summary["data_categories"][0]["id"] == "files"

    def test_denial_detail_never_contains_payload(self) -> None:
        decision = evaluate_transmission(
            PrivacyPolicy(),
            TransmissionRequest("openai", ("prompt",), purpose=MARKER_SECRET),
        )
        # ``detail`` is a fixed explanation: request free text is not interpolated.
        assert MARKER_SECRET not in decision.detail
        assert "disabled" in decision.detail


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class TestGate:
    def test_gate_raises_on_denied_transmission(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            assert_transmission_allowed(
                PrivacyPolicy(), TransmissionRequest("openai", ("prompt",))
            )
        assert exc.value.code == ErrorCode.PRIVACY_TRANSMISSION_DENIED
        assert exc.value.user_action_required is True

    def test_gate_returns_decision_when_allowed(self) -> None:
        decision = assert_transmission_allowed(
            _open_policy(), TransmissionRequest("openai", ("prompt",))
        )
        assert decision.allowed is True

    def test_gate_error_details_are_sanitized(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            assert_transmission_allowed(
                PrivacyPolicy(),
                TransmissionRequest("openai", ("prompt",), purpose=MARKER_SECRET),
            )
        diagnostic = json.dumps(exc.value.to_diagnostic_dict())
        assert MARKER_SECRET not in diagnostic
        assert "external_transmission_disabled" in diagnostic


# ---------------------------------------------------------------------------
# Policy from config
# ---------------------------------------------------------------------------


class TestPolicyFromConfig:
    def test_defaults_are_restrictive(self) -> None:
        policy = PrivacyPolicy.from_config(PrivacyConfig())
        assert policy.allow_external_transmission is False
        assert policy.local_only is False
        assert policy.require_confirmation is True
        assert policy.allowed_providers == frozenset()
        assert policy.redact_before_transmission is True

    def test_reads_config_fields(self) -> None:
        config = PrivacyConfig(
            allow_external_transmission=True,
            local_only=True,
            require_confirmation=False,
            allowed_providers=["openai", "anthropic"],
            redact_before_transmission=False,
        )
        policy = PrivacyPolicy.from_config(config)
        assert policy.allow_external_transmission is True
        assert policy.local_only is True
        assert policy.require_confirmation is False
        assert policy.allowed_providers == frozenset({"openai", "anthropic"})
        assert policy.redact_before_transmission is False

    def test_policy_dict_has_no_secrets(self) -> None:
        # Whitelist: the serialized policy has no free-text field at all.
        assert set(PrivacyPolicy().to_dict()) == {
            "allow_external_transmission",
            "local_only",
            "require_confirmation",
            "allowed_providers",
            "redact_before_transmission",
        }


# ---------------------------------------------------------------------------
# Redaction before transmission
# ---------------------------------------------------------------------------


class TestPreparePayload:
    def test_pattern_secret_redacted(self) -> None:
        result = prepare_payload("key sk-abcdef1234567890abcdef", PrivacyPolicy())
        assert "sk-abcdef1234567890abcdef" not in result
        assert "[REDACTED]" in result

    def test_known_secret_redacted(self) -> None:
        payload = f"remember {MARKER_SECRET} forever"
        result = prepare_payload(payload, PrivacyPolicy(), known_secrets=[MARKER_SECRET])
        assert MARKER_SECRET not in result

    def test_redaction_can_be_disabled_by_policy(self) -> None:
        payload = "key sk-abcdef1234567890abcdef"
        policy = PrivacyPolicy(redact_before_transmission=False)
        assert prepare_payload(payload, policy) == payload
