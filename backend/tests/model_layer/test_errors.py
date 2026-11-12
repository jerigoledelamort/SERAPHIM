# S12 tests — normalized provider errors and auth-leakage guarantees.

import pytest
from seraphim.model_layer.errors import (
    KIND_DEFAULTS,
    KIND_TO_CODE,
    ProviderError,
    ProviderErrorKind,
    provider_auth_error,
    provider_cancelled_error,
    provider_capability_error,
    provider_request_invalid_error,
    provider_response_invalid_error,
    provider_timeout_error,
    provider_unavailable_error,
)

SECRET = "sk-" + "Z" * 24


class TestKindMapping:
    def test_every_kind_maps_to_a_code(self) -> None:
        for kind in ProviderErrorKind:
            assert kind in KIND_TO_CODE
            assert kind in KIND_DEFAULTS

    def test_unknown_kind_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError):
            ProviderError("not_a_kind")

    def test_auth_is_not_retryable_and_needs_user(self) -> None:
        err = provider_auth_error("openai")
        assert err.retryable is False
        assert err.user_action_required is True
        assert err.code == "PROVIDER_AUTH_FAILED"

    def test_timeout_is_retryable(self) -> None:
        err = provider_timeout_error("openai")
        assert err.retryable is True
        assert err.user_action_required is False
        assert err.code == "PROVIDER_TIMEOUT"

    def test_cancelled_is_not_retryable(self) -> None:
        err = provider_cancelled_error("openai")
        assert err.retryable is False
        assert err.code == "PROVIDER_CANCELLED"

    def test_component_includes_provider_id(self) -> None:
        assert provider_unavailable_error("local").component == "model_layer.local"
        assert ProviderError(ProviderErrorKind.TIMEOUT).component == "model_layer"

    def test_overrides_are_honoured(self) -> None:
        err = ProviderError(ProviderErrorKind.TIMEOUT, "p", retryable=False)
        assert err.retryable is False

    def test_capability_error_carries_feature(self) -> None:
        err = provider_capability_error("p", "vision")
        assert err.sanitized_details["feature"] == "vision"


class TestNoAuthLeakage:
    def test_key_in_safe_message_is_redacted(self) -> None:
        err = provider_auth_error("openai", safe_message=f"invalid key {SECRET}")
        assert SECRET not in err.safe_message
        assert SECRET not in str(err)

    def test_key_never_in_user_facing_dict(self) -> None:
        err = provider_auth_error("openai", safe_message=f"key={SECRET}")
        # to_dict() never carries free text at all; assert the whole surface.
        dumped = repr(err.to_dict()) + repr(err.to_diagnostic_dict()) + str(err)
        assert SECRET not in dumped

    def test_key_in_provider_id_is_scrubbed(self) -> None:
        # ``provider_id`` becomes the user-facing ``component`` value.
        err = provider_auth_error(SECRET)
        assert SECRET not in err.component
        assert SECRET not in repr(err.to_dict())

    def test_key_never_in_diagnostic_dict(self) -> None:
        err = provider_auth_error("openai", safe_message=f"bearer {SECRET}")
        dumped = repr(err.to_diagnostic_dict())
        assert SECRET not in dumped

    def test_key_in_details_is_redacted(self) -> None:
        err = provider_request_invalid_error(
            "openai", safe_message="bad"
        )
        err2 = ProviderError(
            ProviderErrorKind.INVALID_REQUEST,
            "openai",
            details={"echoed": SECRET, "api_key": SECRET},
        )
        assert SECRET not in repr(err2.sanitized_details)
        assert err.sanitized_details == {}

    def test_user_facing_dict_has_no_diagnostics(self) -> None:
        err = provider_response_invalid_error("openai", safe_message="bad json")
        d = err.to_dict()
        assert set(d) == {
            "code",
            "message_key",
            "component",
            "retryable",
            "user_action_required",
            "details_ref",
        }

    def test_key_in_diagnostic_correlation_fields_is_scrubbed(self) -> None:
        # correlation_id/task_id are caller-supplied free text.
        err = ProviderError(
            ProviderErrorKind.AUTH,
            "p",
            correlation_id=SECRET,
            task_id=SECRET,
        )
        assert SECRET not in repr(err.to_diagnostic_dict())

    def test_message_key_is_localizable(self) -> None:
        err = provider_timeout_error("p")
        assert err.message_key == "errors.provider_timeout"
