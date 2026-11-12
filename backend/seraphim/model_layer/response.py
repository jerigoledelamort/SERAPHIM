# SERAPHIM MODEL LAYER — normalized model response (S12).
#
# This is the common response contract CORE/COMPASS consume.  It carries only
# provider-independent fields; anything a specific provider reports beyond that
# is placed in ``metadata["provider"][<provider_id>]`` and is never interpreted
# by CORE.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_dict, sanitize_text
from seraphim.contracts.timestamps import now_utc
from seraphim.model_layer.content import ContentPart, TextPart, part_from_dict
from seraphim.model_layer.errors import provider_response_invalid_error
from seraphim.model_layer.versioning import (
    check_schema_version,
    require,
    require_mapping,
    split_known,
)


class FinishReason(StrEnum):
    """Why generation stopped, normalized across providers."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    REFUSAL = "refusal"
    ERROR = "error"


@dataclass
class Usage:
    """Token/cost metadata.  Cost is only set when the provider reports it."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        for name in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SeraphimError(
                    code=ErrorCode.VALIDATION_FAILED,
                    component="model_layer.response",
                    safe_message=f"Usage.{name} must be a non-negative int, got {value!r}",
                )
        if self.total_tokens == 0 and (self.prompt_tokens or self.completion_tokens):
            self.total_tokens = self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Usage:
        return cls(
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            cached_tokens=data.get("cached_tokens", 0),
            cost_usd=data.get("cost_usd"),
        )


@dataclass
class ToolCall:
    """A normalized tool call requested by the model.

    ``arguments`` is always a parsed JSON object; ``raw_arguments`` keeps the
    original string for diagnostics.  An incomplete/invalid argument payload is
    never turned into a callable ToolCall (S14 owns full validation).
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ToolCall.id must be a non-empty string",
            )
        if not isinstance(self.name, str) or not self.name:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ToolCall.name must be a non-empty string",
            )
        if not isinstance(self.arguments, dict):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ToolCall.arguments must be a JSON object",
            )

    def to_dict(self) -> dict[str, Any]:
        # ``to_dict`` is a serialization sink: a tool call is untrusted data, so
        # every free-text field is scrubbed here as well as at the source.  A
        # value that reached a ``ToolCall`` by mistake must not be able to leave
        # through a dump (TB-7, S14 review finding M4).
        return {
            "id": sanitize_text(self.id),
            "name": sanitize_text(self.name),
            "arguments": sanitize_dict(dict(self.arguments)),
            "raw_arguments": sanitize_text(self.raw_arguments),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        return cls(
            id=require(data, "id", "ToolCall"),
            name=require(data, "name", "ToolCall"),
            arguments=data.get("arguments", {}),
            raw_arguments=data.get("raw_arguments", ""),
        )


def normalize_tool_calls(raw_calls: list[dict[str, Any]], provider_id: str = "") -> list[ToolCall]:
    """Turn provider-shaped raw tool calls into normalized ``ToolCall`` objects.

    Accepts ``arguments`` as either a JSON object or a JSON string.  A malformed
    string, a missing id/name, or a non-object argument payload raises a
    normalized ``RESPONSE_FORMAT_INVALID`` error instead of producing a partial
    call (a tool must never run on unvalidated arguments).
    """
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, dict):
            raise provider_response_invalid_error(
                provider_id, safe_message=f"tool call #{index} is not an object"
            )
        call_id = raw.get("id") or ""
        if not isinstance(call_id, str):
            call_id = f"{provider_id}_call_{index}"
        name = raw.get("name") or ""
        if not isinstance(name, str):
            raise provider_response_invalid_error(
                provider_id,
                safe_message=f"tool call #{index} has a non-string name",
            )
        if not call_id or not name:
            raise provider_response_invalid_error(
                provider_id, safe_message=f"tool call #{index} is missing id or name"
            )
        args = raw.get("arguments", {})
        raw_arguments = ""
        if isinstance(args, str):
            raw_arguments = args
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                raise provider_response_invalid_error(
                    provider_id,
                    safe_message=f"tool call {name!r} has malformed JSON arguments",
                ) from None
        if not isinstance(args, dict):
            raise provider_response_invalid_error(
                provider_id,
                safe_message=f"tool call {name!r} arguments must be a JSON object",
            )
        calls.append(
            ToolCall(id=call_id, name=name, arguments=args, raw_arguments=raw_arguments)
        )
    return calls


@dataclass
class ModelResponse:
    """The common response contract for every provider.

    ``metadata`` is sanitized at construction.  Provider-specific data must be
    nested under ``metadata["provider"][provider_id]`` so that CORE can ignore
    it entirely.
    """

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    id: str
    model: str
    provider: str
    content: list[ContentPart] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = FinishReason.STOP
    usage: Usage = field(default_factory=Usage)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.id:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ModelResponse.id must not be empty",
            )
        if not self.provider:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ModelResponse.provider must not be empty",
            )
        if not self.model:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message="ModelResponse.model must not be empty",
            )
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or not self.MIN_SUPPORTED_VERSION <= self.schema_version <= self.SCHEMA_VERSION
        ):
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="model_layer.response",
                safe_message=(
                    f"ModelResponse schema_version {self.schema_version!r} outside supported "
                    f"range [{self.MIN_SUPPORTED_VERSION}, {self.SCHEMA_VERSION}]"
                ),
                user_action_required=True,
            )
        if not isinstance(self.finish_reason, str) or self.finish_reason not in set(FinishReason):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.response",
                safe_message=(
                    f"Invalid finish_reason: {self.finish_reason!r}. Must be one of "
                    f"{[r.value for r in FinishReason]}"
                ),
            )
        if not self.created_at:
            self.created_at = now_utc()
        # Provider extras must never smuggle a credential into a response dump.
        if self.metadata:
            self.metadata = sanitize_dict(
                require_mapping(self.metadata, "metadata", "ModelResponse")
            )

    # -- Queries -------------------------------------------------------------

    def text(self) -> str:
        """Concatenated text parts (images/tool results excluded)."""
        return "".join(p.text for p in self.content if isinstance(p, TextPart))

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def provider_metadata(self, provider_id: str | None = None) -> dict[str, Any]:
        """Return namespaced provider extras (empty if none)."""
        provider_block = self.metadata.get("provider", {})
        if not isinstance(provider_block, dict):
            return {}
        if provider_id is None:
            return provider_block
        value = provider_block.get(provider_id, {})
        return value if isinstance(value, dict) else {}

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "id": self.id,
            "model": self.model,
            "provider": self.provider,
            "content": [p.to_dict() for p in self.content],
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "finish_reason": self.finish_reason,
            "usage": self.usage.to_dict(),
            "created_at": self.created_at,
            # Sanitized again here: the dataclass is mutable, so metadata could
            # be written after construction (S12 review finding m3).
            "metadata": sanitize_dict(self.metadata) if self.metadata else {},
        }
        # Unknown fields are sanitized as well: an unknown field is still an
        # output sink (S12 review finding MINOR C).
        extra = getattr(self, "_extra_fields", {})
        if extra:
            result.update(sanitize_dict(extra))
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelResponse:
        version = check_schema_version(
            data, "ModelResponse", cls.SCHEMA_VERSION, cls.MIN_SUPPORTED_VERSION
        )
        kwargs, extra = split_known(
            data,
            {
                "schema_version",
                "id",
                "model",
                "provider",
                "content",
                "tool_calls",
                "finish_reason",
                "usage",
                "created_at",
                "metadata",
            },
            "ModelResponse",
        )
        obj = cls(
            id=require(kwargs, "id", "ModelResponse"),
            model=require(kwargs, "model", "ModelResponse"),
            provider=require(kwargs, "provider", "ModelResponse"),
            content=[part_from_dict(p) for p in kwargs.get("content", [])],
            tool_calls=[ToolCall.from_dict(c) for c in kwargs.get("tool_calls", [])],
            finish_reason=kwargs.get("finish_reason", FinishReason.STOP),
            usage=Usage.from_dict(kwargs.get("usage", {})),
            created_at=kwargs.get("created_at", ""),
            metadata=kwargs.get("metadata", {}),
            schema_version=version,
        )
        object.__setattr__(obj, "_extra_fields", extra)
        return obj
