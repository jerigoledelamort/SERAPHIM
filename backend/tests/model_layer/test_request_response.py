# S12 tests — normalized request/response, usage and tool call normalization.

import json

import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.model_layer.content import (
    ImagePart,
    Message,
    PartKind,
    TextPart,
    ToolResultPart,
    part_from_dict,
)
from seraphim.model_layer.errors import ProviderError, ProviderErrorKind
from seraphim.model_layer.request import ModelRequest, ToolSpec
from seraphim.model_layer.response import (
    FinishReason,
    ModelResponse,
    ToolCall,
    Usage,
    normalize_tool_calls,
)


class TestMessage:
    def test_factories(self) -> None:
        assert Message.system("s").role == "system"
        assert Message.user("u").text() == "u"
        assert Message.assistant("a").text() == "a"

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            Message(role="wizard", content=[TextPart("x")])

    def test_tool_message_requires_call_id(self) -> None:
        with pytest.raises(SeraphimError):
            Message(role="tool", content=[])
        msg = Message.tool_result("call_1", "ok")
        assert msg.tool_call_id == "call_1"
        assert msg.content[0].kind == PartKind.TOOL_RESULT

    def test_round_trip(self) -> None:
        msg = Message(role="user", content=[TextPart("hi"), ImagePart(mime_type="image/png", data_ref="img_1")])
        restored = Message.from_dict(msg.to_dict())
        assert restored.role == "user"
        assert restored.text() == "hi"
        assert len(restored.images()) == 1
        assert restored.images()[0].data_ref == "img_1"

    def test_image_requires_payload(self) -> None:
        with pytest.raises(SeraphimError):
            ImagePart(mime_type="image/png")

    def test_image_data_is_not_serialized(self) -> None:
        part = ImagePart(mime_type="image/png", data="BASE64BYTES")
        assert "data" not in part.to_dict()

    def test_unknown_part_kind_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            part_from_dict({"kind": "hologram"})

    def test_image_and_tool_result_parts_round_trip(self) -> None:
        image = part_from_dict({"kind": "image", "mime_type": "image/png", "data_ref": "i"})
        assert isinstance(image, ImagePart)
        tool = part_from_dict({"kind": "tool_result", "tool_call_id": "c1", "content": "ok"})
        assert isinstance(tool, ToolResultPart)

    def test_part_missing_required_field_is_normalized(self) -> None:
        with pytest.raises(SeraphimError):
            part_from_dict({"kind": "image"})
        with pytest.raises(SeraphimError):
            part_from_dict({"kind": "tool_result"})

    def test_message_content_must_be_a_list(self) -> None:
        # A non-iterable is the case the guard actually catches: a string would
        # already fail the part-type check (S12 review MINOR E).
        with pytest.raises(SeraphimError):
            Message(role="user", content=42)

    def test_message_content_rejects_foreign_parts(self) -> None:
        with pytest.raises(SeraphimError):
            Message(role="user", content=["plain string"])

    def test_request_metadata_must_be_an_object(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], metadata="not a dict")

    def test_request_metadata_sanitized_on_serialization(self) -> None:
        req = ModelRequest(messages=[Message.user("x")])
        req.metadata["api_key"] = "sk-" + "g" * 20
        assert "sk-" not in repr(req.to_dict())

    def test_unknown_field_is_sanitized_on_serialization(self) -> None:
        payload = ModelRequest(messages=[Message.user("x")]).to_dict()
        payload["future_api_key"] = "sk-" + "h" * 20
        restored = ModelRequest.from_dict(payload)
        assert "sk-" not in repr(restored.to_dict())

    def test_bool_is_not_accepted_as_temperature(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], temperature=True)


class TestModelRequest:
    def test_requires_messages(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[])

    def test_temperature_bounds(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], temperature=3.0)
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], temperature=-0.1)

    def test_top_p_bounds(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], top_p=1.5)

    def test_max_output_tokens_rejects_non_positive(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], max_output_tokens=0)
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], max_output_tokens=-3)

    def test_response_schema_must_be_object(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], response_schema="string")

    def test_metadata_is_sanitized(self) -> None:
        req = ModelRequest(
            messages=[Message.user("x")], metadata={"api_key": "sk-" + "b" * 20}
        )
        assert req.metadata["api_key"] == "[REDACTED]"

    def test_missing_schema_version_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest.from_dict({"messages": [Message.user("x").to_dict()]})

    def test_future_schema_version_rejected(self) -> None:
        payload = ModelRequest(messages=[Message.user("x")]).to_dict()
        payload["schema_version"] = 99
        with pytest.raises(SeraphimError) as exc:
            ModelRequest.from_dict(payload)
        assert exc.value.code == "CONTRACT_VERSION_UNSUPPORTED"

    def test_too_old_schema_version_rejected(self) -> None:
        payload = ModelRequest(messages=[Message.user("x")]).to_dict()
        payload["schema_version"] = 0
        with pytest.raises(SeraphimError) as exc:
            ModelRequest.from_dict(payload)
        assert exc.value.code == "CONTRACT_VERSION_UNSUPPORTED"

    def test_non_int_schema_version_rejected(self) -> None:
        payload = ModelRequest(messages=[Message.user("x")]).to_dict()
        payload["schema_version"] = "1"
        with pytest.raises(SeraphimError) as exc:
            ModelRequest.from_dict(payload)
        assert exc.value.code == "VALIDATION_FAILED"

    def test_unknown_optional_field_survives_round_trip(self) -> None:
        payload = ModelRequest(messages=[Message.user("x")]).to_dict()
        payload["future_hint"] = "keep me"
        restored = ModelRequest.from_dict(payload)
        assert restored.to_dict()["future_hint"] == "keep me"

    def test_missing_message_role_is_normalized(self) -> None:
        with pytest.raises(SeraphimError):
            Message.from_dict({"content": []})

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(SeraphimError):
            ModelRequest(messages=[Message.user("x")], timeout_seconds=0)

    def test_estimated_tokens_grows_with_text(self) -> None:
        small = ModelRequest(messages=[Message.user("hi")])
        large = ModelRequest(messages=[Message.user("x" * 400)])
        assert large.estimated_prompt_tokens() > small.estimated_prompt_tokens()

    def test_round_trip(self) -> None:
        req = ModelRequest(
            messages=[Message.user("hi")],
            model="m",
            tools=[ToolSpec(name="t", description="d", parameters={"type": "object"})],
            temperature=0.5,
            stream=True,
            metadata={"task_id": "task_1"},
        )
        restored = ModelRequest.from_dict(req.to_dict())
        assert restored.model == "m"
        assert restored.tools[0].name == "t"
        assert restored.stream is True
        assert restored.metadata == {"task_id": "task_1"}

    def test_tool_spec_requires_name(self) -> None:
        with pytest.raises(SeraphimError):
            ToolSpec(name="")


class TestUsage:
    def test_total_computed(self) -> None:
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        assert usage.total_tokens == 15

    def test_negative_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            Usage(prompt_tokens=-1)

    def test_round_trip(self) -> None:
        usage = Usage(prompt_tokens=3, completion_tokens=4, cost_usd=0.01)
        assert Usage.from_dict(usage.to_dict()) == usage


class TestStreamEventEnvelope:
    def test_to_dict_shape(self) -> None:
        from seraphim.model_layer.stream import StreamEvent, StreamEventType

        event = StreamEvent(type=StreamEventType.TEXT_DELTA, sequence=2, text_delta="hi")
        dumped = event.to_dict()
        assert dumped["type"] == "text_delta"
        assert dumped["sequence"] == 2
        assert dumped["text_delta"] == "hi"
        assert dumped["error"] is None

    def test_raw_error_is_sanitized(self) -> None:
        from seraphim.model_layer.stream import StreamEvent, StreamEventType

        secret = "sk-" + "D" * 24
        event = StreamEvent(type=StreamEventType.ERROR, error=RuntimeError(f"boom {secret}"))
        assert secret not in repr(event.to_dict())

    def test_metadata_is_sanitized(self) -> None:
        from seraphim.model_layer.stream import StreamEvent, StreamEventType

        event = StreamEvent(type=StreamEventType.START, metadata={"api_key": "sk-" + "e" * 20})
        assert event.to_dict()["metadata"]["api_key"] == "[REDACTED]"


class TestProviderHealth:
    def test_round_trip(self) -> None:
        from seraphim.model_layer.health import HealthStatus, ProviderHealth

        health = ProviderHealth(
            status=HealthStatus.DEGRADED, provider_id="p", model="m", latency_ms=1.5
        )
        restored = ProviderHealth.from_dict(health.to_dict())
        assert restored.status == HealthStatus.DEGRADED
        assert restored.latency_ms == 1.5

    def test_detail_and_metadata_are_sanitized(self) -> None:
        from seraphim.model_layer.health import ProviderHealth

        secret = "sk-" + "F" * 24
        health = ProviderHealth(
            status="ONLINE", detail=f"token {secret}", metadata={"api_key": secret}
        )
        assert secret not in health.detail
        assert secret not in repr(health.to_dict())

    def test_detail_sanitized_on_serialization(self) -> None:
        from seraphim.model_layer.health import ProviderHealth

        secret = "sk-" + "I" * 24
        health = ProviderHealth(status="ONLINE")
        health.detail = f"token {secret}"
        health.metadata["api_key"] = secret
        assert secret not in repr(health.to_dict())


class TestToolCallNormalization:
    def test_object_arguments(self) -> None:
        calls = normalize_tool_calls([{"id": "c1", "name": "t", "arguments": {"a": 1}}])
        assert calls[0].arguments == {"a": 1}

    def test_json_string_arguments(self) -> None:
        calls = normalize_tool_calls(
            [{"id": "c1", "name": "t", "arguments": json.dumps({"a": 1})}]
        )
        assert calls[0].arguments == {"a": 1}
        assert calls[0].raw_arguments == '{"a": 1}'

    def test_malformed_json_rejected(self) -> None:
        with pytest.raises(ProviderError) as exc:
            normalize_tool_calls([{"id": "c1", "name": "t", "arguments": "{not json"}])
        assert exc.value.kind == ProviderErrorKind.RESPONSE_INVALID
        assert exc.value.code == "RESPONSE_FORMAT_INVALID"

    def test_missing_id_rejected(self) -> None:
        with pytest.raises(ProviderError):
            normalize_tool_calls([{"name": "t", "arguments": {}}])

    def test_non_object_arguments_rejected(self) -> None:
        with pytest.raises(ProviderError):
            normalize_tool_calls([{"id": "c1", "name": "t", "arguments": [1, 2]}])

    def test_tool_call_requires_name(self) -> None:
        with pytest.raises(SeraphimError):
            ToolCall(id="c1", name="")


class TestModelResponse:
    def _response(self, **kwargs) -> ModelResponse:
        base = {"id": "r1", "model": "m", "provider": "p"}
        base.update(kwargs)
        return ModelResponse(**base)

    def test_text_concatenation(self) -> None:
        resp = self._response(content=[TextPart("a"), TextPart("b")])
        assert resp.text() == "ab"

    def test_invalid_finish_reason_rejected(self) -> None:
        with pytest.raises(SeraphimError):
            self._response(finish_reason="exploded")

    def test_requires_provider_and_id(self) -> None:
        with pytest.raises(SeraphimError):
            ModelResponse(id="", model="m", provider="p")
        with pytest.raises(SeraphimError):
            ModelResponse(id="r", model="m", provider="")

    def test_round_trip(self) -> None:
        resp = self._response(
            content=[TextPart("hello")],
            tool_calls=[ToolCall(id="c1", name="t", arguments={"a": 1})],
            finish_reason=FinishReason.TOOL_CALLS,
            usage=Usage(prompt_tokens=1, completion_tokens=2),
        )
        restored = ModelResponse.from_dict(resp.to_dict())
        assert restored.text() == "hello"
        assert restored.tool_calls[0].name == "t"
        assert restored.usage.total_tokens == 3
        assert restored.finish_reason == FinishReason.TOOL_CALLS

    def test_provider_metadata_is_namespaced(self) -> None:
        resp = self._response(metadata={"provider": {"p": {"raw": "x"}}})
        assert resp.provider_metadata("p") == {"raw": "x"}
        assert resp.provider_metadata("other") == {}

    def test_metadata_is_sanitized(self) -> None:
        # A provider must not be able to smuggle a key into a response dump.
        resp = self._response(metadata={"provider": {"p": {"api_key": "sk-" + "a" * 20}}})
        assert resp.metadata["provider"]["p"]["api_key"] == "[REDACTED]"

    def test_created_at_defaulted(self) -> None:
        assert self._response().created_at

    def test_model_required(self) -> None:
        with pytest.raises(SeraphimError):
            ModelResponse(id="r", model="", provider="p")

    def test_metadata_sanitized_on_serialization(self) -> None:
        # The dataclass is mutable; a late write must not reach a dump.
        resp = self._response()
        resp.metadata["provider"] = {"p": {"api_key": "sk-" + "c" * 20}}
        assert "sk-" not in repr(resp.to_dict())

    def test_future_schema_version_rejected(self) -> None:
        payload = self._response().to_dict()
        payload["schema_version"] = 99
        with pytest.raises(SeraphimError) as exc:
            ModelResponse.from_dict(payload)
        assert exc.value.code == "CONTRACT_VERSION_UNSUPPORTED"

    def test_unknown_optional_field_survives_round_trip(self) -> None:
        payload = self._response().to_dict()
        payload["future_hint"] = "keep me"
        assert ModelResponse.from_dict(payload).to_dict()["future_hint"] == "keep me"

    def test_missing_required_field_is_normalized(self) -> None:
        payload = self._response().to_dict()
        del payload["provider"]
        with pytest.raises(SeraphimError):
            ModelResponse.from_dict(payload)
