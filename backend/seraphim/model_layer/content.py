# SERAPHIM MODEL LAYER — normalized message/content parts (S12).
#
# These are provider-independent representations.  A provider adapter maps its
# own wire format onto these types; CORE only ever sees these types.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer.versioning import require


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class PartKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    TOOL_RESULT = "tool_result"


@dataclass
class TextPart:
    text: str

    kind: str = field(default=PartKind.TEXT, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextPart:
        return cls(text=data.get("text", ""))


@dataclass
class ImagePart:
    """An image reference, not raw provider payload.

    ``data_ref`` points at an artifact/EYES reference; ``data`` optionally holds
    base64 bytes for providers that inline images.  Keeping the reference keeps
    provider-specific encoding out of the message contract.
    """

    mime_type: str
    data_ref: str = ""
    data: str = ""

    kind: str = field(default=PartKind.IMAGE, init=False)

    def __post_init__(self) -> None:
        if not self.mime_type:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message="ImagePart.mime_type must not be empty",
            )
        if not self.data_ref and not self.data:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message="ImagePart requires data_ref or data",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mime_type": self.mime_type,
            "data_ref": self.data_ref,
            # ``data`` is intentionally not serialized: a diagnostic dump must
            # not embed raw image bytes.
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImagePart:
        return cls(
            mime_type=require(data, "mime_type", "ImagePart"),
            data_ref=data.get("data_ref", ""),
            data=data.get("data", ""),
        )


@dataclass
class ToolResultPart:
    """Result of a tool call, fed back to the model on the next turn."""

    tool_call_id: str
    content: str = ""
    is_error: bool = False

    kind: str = field(default=PartKind.TOOL_RESULT, init=False)

    def __post_init__(self) -> None:
        if not self.tool_call_id:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message="ToolResultPart.tool_call_id must not be empty",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_call_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResultPart:
        return cls(
            tool_call_id=require(data, "tool_call_id", "ToolResultPart"),
            content=data.get("content", ""),
            is_error=data.get("is_error", False),
        )


ContentPart = TextPart | ImagePart | ToolResultPart


def part_from_dict(data: dict[str, Any]) -> ContentPart:
    kind = data.get("kind", PartKind.TEXT)
    if kind == PartKind.TEXT:
        return TextPart.from_dict(data)
    if kind == PartKind.IMAGE:
        return ImagePart.from_dict(data)
    if kind == PartKind.TOOL_RESULT:
        return ToolResultPart.from_dict(data)
    raise SeraphimError(
        code=ErrorCode.VALIDATION_FAILED,
        component="model_layer.content",
        safe_message=f"Unknown content part kind: {kind!r}",
    )


@dataclass
class Message:
    """A single normalized chat message.

    ``tool_calls`` carries the calls an *assistant* message asked for, so a
    multi-turn tool loop can be replayed to the provider: an OpenAI-compatible
    server expects the assistant turn that requested a tool to name the calls the
    following ``tool`` messages answer (C5 review D7).  A user/system/tool message
    leaves it empty.
    """

    role: str
    content: list[ContentPart] = field(default_factory=list)
    name: str = ""
    tool_call_id: str = ""
    tool_calls: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or self.role not in set(Role):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message=(
                    f"Invalid message role: {self.role!r}. Must be one of "
                    f"{[r.value for r in Role]}"
                ),
            )
        if not isinstance(self.content, (list, tuple)):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message=(
                    f"Message.content must be a list of parts, got "
                    f"{type(self.content).__name__}"
                ),
            )
        if not all(isinstance(p, (TextPart, ImagePart, ToolResultPart)) for p in self.content):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message="Message.content may only contain TextPart/ImagePart/ToolResultPart",
            )
        if self.role == Role.TOOL and not self.tool_call_id:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message="A tool message requires tool_call_id",
            )
        if not isinstance(self.tool_calls, (list, tuple)):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component="model_layer.content",
                safe_message=(
                    f"Message.tool_calls must be a list, got {type(self.tool_calls).__name__}"
                ),
            )
        if self.tool_calls:
            # The element type lives in ``response`` (which imports this module),
            # so the check is deferred and structural: a call must expose the same
            # three fields a ``ToolCall`` does.  A non-assistant message carrying
            # calls is a shape error a provider would reject with an opaque 400.
            for call in self.tool_calls:
                if not all(hasattr(call, name) for name in ("id", "name", "arguments")):
                    raise SeraphimError(
                        code=ErrorCode.VALIDATION_FAILED,
                        component="model_layer.content",
                        safe_message="Message.tool_calls may only contain ToolCall objects",
                    )
            if self.role != Role.ASSISTANT:
                raise SeraphimError(
                    code=ErrorCode.VALIDATION_FAILED,
                    component="model_layer.content",
                    safe_message="Only an assistant message can carry tool_calls",
                )

    # -- Factories -----------------------------------------------------------

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role=Role.SYSTEM, content=[TextPart(text)])

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=[TextPart(text)])

    @classmethod
    def assistant(cls, text: str, tool_calls: list[Any] | None = None) -> Message:
        """An assistant turn, optionally carrying the tool calls it requested.

        Feeding a provider response's ``tool_calls`` back as the next request's
        assistant message is what lets a tool loop continue: without it the
        following ``tool`` result refers to a call the history never made.
        """
        return cls(
            role=Role.ASSISTANT,
            content=[TextPart(text)] if text else [],
            tool_calls=list(tool_calls or []),
        )

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str, *, is_error: bool = False) -> Message:
        return cls(
            role=Role.TOOL,
            tool_call_id=tool_call_id,
            content=[ToolResultPart(tool_call_id, content, is_error)],
        )

    # -- Queries -------------------------------------------------------------

    def text(self) -> str:
        """Concatenate the text parts (ignoring images/tool results)."""
        return "".join(p.text for p in self.content if isinstance(p, TextPart))

    def images(self) -> list[ImagePart]:
        return [p for p in self.content if isinstance(p, ImagePart)]

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": self.role,
            "content": [p.to_dict() for p in self.content],
            "name": self.name,
            "tool_call_id": self.tool_call_id,
        }
        if self.tool_calls:
            data["tool_calls"] = [c.to_dict() for c in self.tool_calls]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        # ``ToolCall`` lives in ``response`` (a one-way import would be a cycle),
        # so it is resolved when a history dump actually carries calls.
        from seraphim.model_layer.response import ToolCall

        return cls(
            role=require(data, "role", "Message"),
            content=[part_from_dict(p) for p in data.get("content", [])],
            name=data.get("name", ""),
            tool_call_id=data.get("tool_call_id", ""),
            tool_calls=[ToolCall.from_dict(c) for c in data.get("tool_calls", [])],
        )
