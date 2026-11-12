# SERAPHIM MODEL LAYER — normalized model request (S12).
#
# A ModelRequest is the single shape CORE/COMPASS hand to any provider.  It has
# no provider-specific fields; provider extras (if any) live in ``metadata``
# under a namespaced key and are never interpreted by CORE.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_dict
from seraphim.model_layer.content import ContentPart, ImagePart, Message, part_from_dict
from seraphim.model_layer.versioning import (
    check_schema_version,
    require,
    require_mapping,
    split_known,
)

#: Rough characters-per-token heuristic used only for a cheap pre-flight
#: context check.  A real provider adapter may replace it with its tokenizer.
_CHARS_PER_TOKEN = 4


@dataclass
class ToolSpec:
    """A tool the model may call, described provider-independently."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message="ToolSpec.name must not be empty",
            )
        if not isinstance(self.parameters, dict):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message="ToolSpec.parameters must be a JSON-schema object",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolSpec:
        return cls(
            name=require(data, "name", "ToolSpec"),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
        )


@dataclass
class ModelRequest:
    """A normalized generation request."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    messages: list[Message] = field(default_factory=list)
    model: str = ""
    tools: list[ToolSpec] = field(default_factory=list)
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    #: JSON schema the response must satisfy (structured output).
    response_schema: dict[str, Any] | None = None
    stream: bool = False
    #: Per-request timeout in seconds. ``None`` = provider default.
    timeout_seconds: float | None = None
    #: Correlation metadata (task_id, session_id, ...).  Not interpreted by the
    #: provider beyond echoing it back in ``ModelResponse.metadata``.
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.messages:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message="ModelRequest requires at least one message",
            )
        if (
            not isinstance(self.schema_version, int)
            or isinstance(self.schema_version, bool)
            or not self.MIN_SUPPORTED_VERSION <= self.schema_version <= self.SCHEMA_VERSION
        ):
            raise SeraphimError(
                code=ErrorCode.CONTRACT_VERSION_UNSUPPORTED,
                component="model_layer.request",
                safe_message=(
                    f"ModelRequest schema_version {self.schema_version!r} outside supported "
                    f"range [{self.MIN_SUPPORTED_VERSION}, {self.SCHEMA_VERSION}]"
                ),
                user_action_required=True,
            )
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not 0.0 <= self.temperature <= 2.0
        ):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message=f"temperature must be a number within [0, 2], got {self.temperature}",
            )
        if self.top_p is not None and (
            isinstance(self.top_p, bool)
            or not isinstance(self.top_p, (int, float))
            or not 0.0 <= self.top_p <= 1.0
        ):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message=f"top_p must be a number within [0, 1], got {self.top_p}",
            )
        if self.max_output_tokens is not None and (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens <= 0
        ):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message=(
                    f"max_output_tokens must be positive, got {self.max_output_tokens}"
                ),
            )
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message=f"timeout_seconds must be positive, got {self.timeout_seconds}",
            )
        if self.response_schema is not None and not isinstance(self.response_schema, dict):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.request",
                safe_message="response_schema must be a JSON-schema object",
            )
        if self.metadata:
            # Symmetry with ModelResponse: a request dump must not be a sink for
            # a credential pasted into metadata by mistake (TB-7).
            self.metadata = sanitize_dict(require_mapping(self.metadata, "metadata", "ModelRequest"))

    # -- Queries -------------------------------------------------------------

    def images(self) -> list[ImagePart]:
        return [img for msg in self.messages for img in msg.images()]

    def has_images(self) -> bool:
        return any(msg.images() for msg in self.messages)

    def estimated_prompt_tokens(self) -> int:
        """Cheap upper-ish estimate for the context pre-flight check."""
        chars = 0
        for msg in self.messages:
            for part in msg.content:
                chars += len(getattr(part, "text", "") or getattr(part, "content", ""))
            chars += len(msg.name)
        return max(1, chars // _CHARS_PER_TOKEN)

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "messages": [m.to_dict() for m in self.messages],
            "model": self.model,
            "tools": [t.to_dict() for t in self.tools],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "response_schema": self.response_schema,
            "stream": self.stream,
            "timeout_seconds": self.timeout_seconds,
            # Sanitized again here: the dataclass is mutable, so metadata could
            # be written after construction (S12 review finding MINOR A).
            "metadata": sanitize_dict(self.metadata) if self.metadata else {},
        }
        # Re-attach unknown fields captured at deserialization (round-trip).
        # They are sanitized too: an unknown field is still an output sink
        # (S12 review finding MINOR C).
        extra = getattr(self, "_extra_fields", {})
        if extra:
            result.update(sanitize_dict(extra))
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelRequest:
        version = check_schema_version(
            data, "ModelRequest", cls.SCHEMA_VERSION, cls.MIN_SUPPORTED_VERSION
        )
        kwargs, extra = split_known(
            data,
            {
                "schema_version",
                "messages",
                "model",
                "tools",
                "temperature",
                "top_p",
                "max_output_tokens",
                "response_schema",
                "stream",
                "timeout_seconds",
                "metadata",
            },
            "ModelRequest",
        )
        obj = cls(
            messages=[Message.from_dict(m) for m in kwargs.get("messages", [])],
            model=kwargs.get("model", ""),
            tools=[ToolSpec.from_dict(t) for t in kwargs.get("tools", [])],
            temperature=kwargs.get("temperature"),
            top_p=kwargs.get("top_p"),
            max_output_tokens=kwargs.get("max_output_tokens"),
            response_schema=kwargs.get("response_schema"),
            stream=kwargs.get("stream", False),
            timeout_seconds=kwargs.get("timeout_seconds"),
            metadata=kwargs.get("metadata", {}),
            schema_version=version,
        )
        # Unknown optional fields are preserved so a round-trip does not lose
        # data written by a newer minor version (CONTRACTS.md §6.1).
        object.__setattr__(obj, "_extra_fields", extra)
        return obj


# Re-exported for callers that build requests from serialized parts.
__all__ = ["ContentPart", "ModelRequest", "ToolSpec", "part_from_dict"]
