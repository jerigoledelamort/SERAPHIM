from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionLimits:
    max_turns: int = 12
    max_calls: int = 24
    max_calls_per_turn: int = 4
    max_arguments_bytes: int = 16384
    max_history_bytes: int = 131072
    max_output_bytes: int = 32768
    max_output_tokens: int = 2048
    timeout_seconds: float = 60

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
            if name != "timeout_seconds" and not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")


@dataclass(frozen=True)
class ExecutionOutcome:
    task_id: str
    status: str
    reason: str = ""
