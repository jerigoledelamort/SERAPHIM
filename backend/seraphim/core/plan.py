# CORE plan schema (S18): a plan is validated data, never free text. A plan that
# fails any check is rejected as a whole; nothing from it is started.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError

MAX_STEPS = 20
MAX_DEPENDS_PER_STEP = 10
MAX_TEXT_LEN = 500
MAX_LIST_ITEMS = 20
MAX_RAW_BYTES = 64 * 1024

RISK_HINTS = ("none", "read", "write", "external", "destructive")
HIGH_RISK_HINTS = frozenset({"external", "destructive"})

_ALLOWED_STEP_KEYS = frozenset(
    {"id", "title", "depends_on", "expected_outputs", "verification", "risk_hint", "max_attempts"}
)
_REQUIRED_STEP_KEYS = frozenset({"id", "title", "verification"})
_ALLOWED_PLAN_KEYS = frozenset({"goal", "constraints", "steps"})
_REQUIRED_PLAN_KEYS = frozenset({"goal", "steps"})


def _invalid(message: str) -> SeraphimError:
    return SeraphimError(
        code=ErrorCode.PLAN_VALIDATION_FAILED,
        component="core.plan",
        safe_message=message,
    )


@dataclass(frozen=True)
class PlanStepSpec:
    id: str
    title: str
    verification: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    risk_hint: str = "none"
    max_attempts: int = 1

    @property
    def needs_aegis_review(self) -> bool:
        return self.risk_hint in HIGH_RISK_HINTS


@dataclass(frozen=True)
class PlanSpec:
    goal: str
    steps: tuple[PlanStepSpec, ...]
    constraints: tuple[str, ...] = ()

    def step(self, step_id: str) -> PlanStepSpec:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)


@dataclass(frozen=True)
class PlanCheck:
    """Result of validating a plan. ``ready`` is the only start gate."""

    errors: tuple[str, ...] = ()
    review_steps: tuple[str, ...] = field(default=())

    @property
    def ready(self) -> bool:
        return not self.errors


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise _invalid(f"Non-standard JSON constant: {name}.")


def parse_plan_json(raw: str) -> PlanSpec:
    """Strict parse and shape check. Raises PLAN_VALIDATION_FAILED on any defect."""
    if not isinstance(raw, str):
        raise _invalid("Plan output is not text.")
    if len(raw.encode("utf-8")) > MAX_RAW_BYTES:
        raise _invalid("Plan output is too large.")
    try:
        data = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise _invalid(f"Plan is not valid JSON (line {exc.lineno}, column {exc.colno}).") from None
    if not isinstance(data, dict):
        raise _invalid("Plan must be a JSON object.")
    return _shape(data)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{where} must be a non-empty string.")
    if len(value) > MAX_TEXT_LEN:
        raise _invalid(f"{where} is longer than {MAX_TEXT_LEN} characters.")
    return value.strip()


def _str_list(value: Any, where: str, *, limit: int = MAX_LIST_ITEMS) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _invalid(f"{where} must be a list.")
    if len(value) > limit:
        raise _invalid(f"{where} has more than {limit} items.")
    return tuple(_text(v, f"{where} item") for v in value)


def _shape(data: dict[str, Any]) -> PlanSpec:
    unknown = set(data) - _ALLOWED_PLAN_KEYS
    if unknown:
        raise _invalid(f"Unknown plan field: {sorted(unknown)[0]}.")
    missing = _REQUIRED_PLAN_KEYS - set(data)
    if missing:
        raise _invalid(f"Plan is missing field: {sorted(missing)[0]}.")
    goal = _text(data["goal"], "goal")
    constraints = _str_list(data.get("constraints"), "constraints")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list):
        raise _invalid("steps must be a list.")
    if not raw_steps:
        raise _invalid("Plan has no steps.")
    if len(raw_steps) > MAX_STEPS:
        raise _invalid(f"Plan has more than {MAX_STEPS} steps.")
    return PlanSpec(goal=goal, constraints=constraints, steps=tuple(_step(s) for s in raw_steps))


def _step(data: Any) -> PlanStepSpec:
    if not isinstance(data, dict):
        raise _invalid("Each step must be an object.")
    unknown = set(data) - _ALLOWED_STEP_KEYS
    if unknown:
        raise _invalid(f"Unknown step field: {sorted(unknown)[0]}.")
    missing = _REQUIRED_STEP_KEYS - set(data)
    if missing:
        raise _invalid(f"Step is missing field: {sorted(missing)[0]}.")
    step_id = _text(data["id"], "step id")
    risk = data.get("risk_hint", "none")
    if risk not in RISK_HINTS:
        raise _invalid(f"Step {step_id} has unknown risk_hint.")
    attempts = data.get("max_attempts", 1)
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
        raise _invalid(f"Step {step_id} max_attempts must be an integer 1..5.")
    depends = _str_list(data.get("depends_on"), f"step {step_id} depends_on", limit=MAX_DEPENDS_PER_STEP)
    verification = _str_list(data["verification"], f"step {step_id} verification")
    if not verification:
        raise _invalid(f"Step {step_id} has no verification criteria.")
    return PlanStepSpec(
        id=step_id,
        title=_text(data["title"], f"step {step_id} title"),
        verification=verification,
        depends_on=depends,
        expected_outputs=_str_list(data.get("expected_outputs"), f"step {step_id} expected_outputs"),
        risk_hint=risk,
        max_attempts=attempts,
    )


def check_plan(plan: PlanSpec) -> PlanCheck:
    """Graph checks. Errors are collected; any error means the plan must not start."""
    errors: list[str] = []
    ids = [s.id for s in plan.steps]
    seen: set[str] = set()
    for step_id in ids:
        if step_id in seen:
            errors.append(f"Duplicate step id: {step_id}.")
        seen.add(step_id)
    known = set(ids)
    for step in plan.steps:
        for dep in step.depends_on:
            if dep == step.id:
                errors.append(f"Step {step.id} depends on itself.")
            elif dep not in known:
                errors.append(f"Step {step.id} depends on missing step {dep}.")
    if not errors:
        cycle = _find_cycle(plan)
        if cycle:
            errors.append(f"Cyclic dependency: {' -> '.join(cycle)}.")
    review = tuple(s.id for s in plan.steps if s.needs_aegis_review)
    return PlanCheck(errors=tuple(errors), review_steps=review)


def _find_cycle(plan: PlanSpec) -> list[str] | None:
    graph = {s.id: s.depends_on for s in plan.steps}
    state: dict[str, int] = {}
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for dep in graph[node]:
            if state.get(dep) == 1:
                return [*path[path.index(dep):], dep]
            if state.get(dep) is None:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node) is None:
            found = visit(node)
            if found:
                return found
    return None
