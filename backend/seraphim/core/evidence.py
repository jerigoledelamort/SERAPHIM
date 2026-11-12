from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CheckSpec:
    kind: str
    target: str = ""
    expected: str = ""
    mandatory: bool = True
    call_id: str = ""

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.kind, self.target, self.expected, self.call_id)):
            raise ValueError("Check fields must be strings")
        if not self.kind or type(self.mandatory) is not bool:
            raise ValueError("Check requires a kind and boolean mandatory flag")


@dataclass(frozen=True)
class Observation:
    passed: bool
    available: bool
    source: str
    details: dict[str, Any] = field(default_factory=dict)


class Verifier(Protocol):
    def __call__(self, check: CheckSpec) -> Observation: ...
