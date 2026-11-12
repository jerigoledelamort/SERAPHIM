# WINGS call format (S19): one ToolCall and one ToolResult shape for every tool.
# A call is a request to run a registered tool; it is not execution. Execution
# is the registry's job, and only after the tool is enabled and its arguments
# pass the input schema.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import validate_id

COMPONENT = "wings.calls"


class CallStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ToolError:
    code: str
    safe_message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not self.code or not self.safe_message:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component=COMPONENT,
                safe_message="ToolError needs a code and a message",
            )

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "safe_message": self.safe_message, "retryable": self.retryable}


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    step_id: str = ""

    def __post_init__(self) -> None:
        validate_id(self.call_id)
        if not self.tool_id.startswith("tool."):
            raise SeraphimError(
                code=ErrorCode.TOOL_NOT_FOUND,
                component=COMPONENT,
                safe_message=f"Tool id must start with tool.: {self.tool_id!r}",
            )
        if not isinstance(self.arguments, dict):
            raise SeraphimError(
                code=ErrorCode.TOOL_SCHEMA_INVALID,
                component=COMPONENT,
                safe_message="Tool arguments must be a JSON object",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "arguments": self.arguments,
            "task_id": self.task_id,
            "step_id": self.step_id,
        }


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_id: str
    status: CallStatus
    duration_ms: int
    output: dict[str, Any] | None = None
    artifact_refs: tuple[str, ...] = ()
    error: ToolError | None = None

    def __post_init__(self) -> None:
        validate_id(self.call_id)
        if self.duration_ms < 0:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component=COMPONENT,
                safe_message="duration_ms must not be negative",
            )
        if self.status is CallStatus.SUCCEEDED and (self.error is not None or self.output is None):
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component=COMPONENT,
                safe_message="SUCCEEDED result needs output and no error",
            )
        if self.status is not CallStatus.SUCCEEDED and self.error is None:
            raise SeraphimError(
                code=ErrorCode.VALIDATION_FAILED,
                component=COMPONENT,
                safe_message=f"{self.status.value} result needs a structured error",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_id": self.tool_id,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "artifact_refs": list(self.artifact_refs),
            "error": self.error.to_dict() if self.error else None,
        }
