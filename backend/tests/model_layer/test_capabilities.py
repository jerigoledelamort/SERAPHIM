# S12 tests — provider capabilities declaration and validation.

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.model_layer.capabilities import (
    AuthKind,
    CapabilityFeature,
    ProviderCapabilities,
)
from seraphim.model_layer.content import ImagePart, Message
from seraphim.model_layer.errors import ProviderError, ProviderErrorKind
from seraphim.model_layer.fake import FakeProvider, FakeTurn
from seraphim.model_layer.provider import ModelProvider
from seraphim.model_layer.request import ModelRequest


class TestCapabilityDeclaration:
    def test_defaults_are_conservative(self) -> None:
        caps = ProviderCapabilities()
        # A provider without an explicit declaration supports chat only.
        assert caps.chat is True
        assert caps.streaming is False
        assert caps.tool_calls is False
        assert caps.vision is False
        assert caps.structured_output is False
        assert caps.context_limit == 0

    def test_supports_known_features(self) -> None:
        caps = ProviderCapabilities(streaming=True, tool_calls=True, vision=True)
        assert caps.supports(CapabilityFeature.CHAT) is True
        assert caps.supports(CapabilityFeature.STREAMING) is True
        assert caps.supports(CapabilityFeature.TOOL_CALLS) is True
        assert caps.supports(CapabilityFeature.VISION) is True
        assert caps.supports(CapabilityFeature.STRUCTURED_OUTPUT) is False

    def test_unknown_feature_is_unsupported_not_assumed(self) -> None:
        caps = ProviderCapabilities()
        assert caps.supports("telepathy") is False
        assert caps.supports("") is False

    def test_cancellation_maps_to_flag(self) -> None:
        assert ProviderCapabilities(supports_cancellation=True).supports(
            CapabilityFeature.CANCELLATION
        )
        assert not ProviderCapabilities(supports_cancellation=False).supports(
            CapabilityFeature.CANCELLATION
        )

    def test_require_raises_normalized_error(self) -> None:
        caps = ProviderCapabilities()
        with pytest.raises(ProviderError) as exc:
            caps.require(CapabilityFeature.VISION, provider_id="p1")
        assert exc.value.kind == ProviderErrorKind.CAPABILITY_UNSUPPORTED
        assert exc.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"
        assert exc.value.user_action_required is True

    def test_require_passes_when_declared(self) -> None:
        ProviderCapabilities(vision=True).require(CapabilityFeature.VISION, provider_id="p1")

    def test_invalid_auth_kind_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            ProviderCapabilities(auth="magic")

    def test_negative_limits_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            ProviderCapabilities(context_limit=-1)
        with pytest.raises(SeraphimError):
            ProviderCapabilities(max_output_tokens=-5)

    def test_round_trip(self) -> None:
        caps = ProviderCapabilities(
            streaming=True,
            tool_calls=True,
            context_limit=8192,
            auth=AuthKind.API_KEY,
            labels=("text", "tools"),
        )
        restored = ProviderCapabilities.from_dict(caps.to_dict())
        assert restored == caps

    def test_no_capability_is_derived_from_model_name(self) -> None:
        # There must be no name-based inference: two providers with the same
        # model name but different declarations stay different.
        a = FakeProvider(model="gpt-4o", capabilities=ProviderCapabilities())
        b = FakeProvider(model="gpt-4o", capabilities=ProviderCapabilities(vision=True))
        assert a.get_capabilities().vision is False
        assert b.get_capabilities().vision is True
        # ...and no name-based constructor exists at all.
        assert not hasattr(ProviderCapabilities, "from_model_name")
        assert not hasattr(ProviderCapabilities, "for_model")


class TestValidateRequest:
    def _request(self, **kwargs) -> ModelRequest:
        return ModelRequest(messages=[Message.user("hi")], **kwargs)

    def test_chat_unsupported(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(chat=False))
        with pytest.raises(ProviderError) as exc:
            provider.validate_request(self._request())
        assert exc.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"

    def test_stream_requires_capability(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(streaming=False))
        with pytest.raises(ProviderError) as exc:
            provider.validate_request(self._request(stream=True))
        assert exc.value.kind == ProviderErrorKind.CAPABILITY_UNSUPPORTED

    def test_tools_require_capability(self) -> None:
        from seraphim.model_layer.request import ToolSpec

        provider = FakeProvider(capabilities=ProviderCapabilities(tool_calls=False))
        with pytest.raises(ProviderError):
            provider.validate_request(
                self._request(tools=[ToolSpec(name="t", parameters={})])
            )

    def test_schema_requires_structured_output(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(structured_output=False))
        with pytest.raises(ProviderError) as exc:
            provider.validate_request(self._request(response_schema={"type": "object"}))
        assert exc.value.kind == ProviderErrorKind.CAPABILITY_UNSUPPORTED

    def test_images_require_vision(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(vision=False))
        req = ModelRequest(
            messages=[Message(role="user", content=[ImagePart(mime_type="image/png", data_ref="a")])]
        )
        with pytest.raises(ProviderError):
            provider.validate_request(req)

    def test_max_images_enforced(self) -> None:
        provider = FakeProvider(
            capabilities=ProviderCapabilities(vision=True, max_images=1)
        )
        req = ModelRequest(
            messages=[
                Message(
                    role="user",
                    content=[
                        ImagePart(mime_type="image/png", data_ref="a"),
                        ImagePart(mime_type="image/png", data_ref="b"),
                    ],
                )
            ]
        )
        with pytest.raises(ProviderError) as exc:
            provider.validate_request(req)
        assert exc.value.kind == ProviderErrorKind.INVALID_REQUEST

    def test_context_limit_enforced(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(context_limit=5))
        req = ModelRequest(messages=[Message.user("x" * 200)])
        with pytest.raises(ProviderError) as exc:
            provider.validate_request(req)
        assert exc.value.kind == ProviderErrorKind.INVALID_REQUEST

    def test_max_output_tokens_enforced(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(max_output_tokens=10))
        with pytest.raises(ProviderError):
            provider.validate_request(self._request(max_output_tokens=11))

    def test_valid_request_passes(self) -> None:
        provider = FakeProvider.success("ok")
        provider.validate_request(self._request(stream=True))

    def test_provider_is_abstract_interface(self) -> None:
        assert issubclass(FakeProvider, ModelProvider)


class TestCapabilityEnforcedOnGeneratePath:
    """The gate must be enforced by ``generate`` itself, not only by the helper.

    Regression guard: if ``FakeProvider.generate`` stopped calling
    ``validate_request``, the direct-call tests above would still pass.
    """

    def _image_request(self) -> ModelRequest:
        return ModelRequest(
            messages=[
                Message(role="user", content=[ImagePart(mime_type="image/png", data_ref="a")])
            ]
        )

    def test_generate_rejects_undeclared_vision(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(vision=False))
        with pytest.raises(ProviderError) as exc:
            provider.generate(self._image_request())
        assert exc.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"

    def test_generate_rejects_undeclared_tools(self) -> None:
        from seraphim.model_layer.request import ToolSpec

        provider = FakeProvider(capabilities=ProviderCapabilities(tool_calls=False))
        with pytest.raises(ProviderError):
            provider.generate(
                ModelRequest(
                    messages=[Message.user("x")],
                    tools=[ToolSpec(name="t", parameters={})],
                )
            )

    def test_generate_rejects_undeclared_schema(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(structured_output=False))
        with pytest.raises(ProviderError):
            provider.generate(
                ModelRequest(messages=[Message.user("x")], response_schema={"type": "object"})
            )

    def test_generate_rejects_undeclared_chat(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(chat=False))
        with pytest.raises(ProviderError):
            provider.generate(ModelRequest(messages=[Message.user("x")]))

    def test_generate_rejects_cancellation_when_not_supported(self) -> None:
        from seraphim.model_layer.cancellation import CancellationToken

        provider = FakeProvider(
            capabilities=ProviderCapabilities(supports_cancellation=False)
        )
        with pytest.raises(ProviderError) as exc:
            provider.generate(ModelRequest(messages=[Message.user("x")]), CancellationToken())
        assert exc.value.sanitized_details.get("feature") == "cancellation"

    def test_cancelled_call_does_not_consume_script(self) -> None:
        from seraphim.model_layer.cancellation import CancellationToken

        provider = FakeProvider(
            script=[FakeTurn(text="scripted")],
            default_text="fallback",
        )
        token = CancellationToken()
        token.cancel()
        with pytest.raises(ProviderError):
            provider.generate(ModelRequest(messages=[Message.user("x")]), token)
        # The scripted turn survives a cancelled call (determinism).
        assert provider.generate(ModelRequest(messages=[Message.user("x")])).text() == "scripted"

    def test_generate_rejects_oversized_context(self) -> None:
        provider = FakeProvider(capabilities=ProviderCapabilities(context_limit=5))
        with pytest.raises(ProviderError) as exc:
            provider.generate(ModelRequest(messages=[Message.user("x" * 200)]))
        assert exc.value.kind == ProviderErrorKind.INVALID_REQUEST
