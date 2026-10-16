# SERAPHIM SANCTUM — deterministic prompt composer (S08).
#
# Composes model instructions from a fixed, ordered set of layers with labeled
# provenance, a size budget, and a separate handling path for untrusted data.
#
# Design guarantees (spec §4.2, §4.3, §9, §12.3; CONTRACTS.md TB-2, TB-10):
#   - The layer order is fixed and identical for every composition.
#   - ``system_policy`` is always first, trusted, and non-overridable.
#   - Untrusted layers (Skill text, retrieved documents) are wrapped in an
#     explicit envelope and their control markers are neutralized, so a Skill
#     or a retrieved file can never escalate to a system-level instruction.
#   - Composition is deterministic: the same inputs always yield the same text
#     (no timestamps, no randomness, no absolute paths).

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_text
from seraphim.sanctum.identity import SYSTEM_POLICY, Identity

COMPONENT = "sanctum.prompt_composer"

# -- Layer identifiers (canonical order = authority order) -------------------

LAYER_SYSTEM_POLICY = "system_policy"
LAYER_SYSTEM_INSTRUCTIONS = "system_instructions"
LAYER_PERSONALITY = "personality"
LAYER_RESPONSE_STYLE = "response_style"
LAYER_PROFILE = "profile"
LAYER_PROJECT_INSTRUCTIONS = "project_instructions"
LAYER_TASK_CONTEXT = "task_context"
LAYER_SKILL_INSTRUCTIONS = "skill_instructions"
LAYER_RETRIEVED_CONTEXT = "retrieved_context"

# Fixed composition order, highest authority first. Never reordered.
LAYER_ORDER: tuple[str, ...] = (
    LAYER_SYSTEM_POLICY,
    LAYER_SYSTEM_INSTRUCTIONS,
    LAYER_PERSONALITY,
    LAYER_RESPONSE_STYLE,
    LAYER_PROFILE,
    LAYER_PROJECT_INSTRUCTIONS,
    LAYER_TASK_CONTEXT,
    LAYER_SKILL_INSTRUCTIONS,
    LAYER_RETRIEVED_CONTEXT,
)

TRUSTED = "trusted"
UNTRUSTED = "untrusted"

TRUST_BY_LAYER: dict[str, str] = {
    LAYER_SYSTEM_POLICY: TRUSTED,
    LAYER_SYSTEM_INSTRUCTIONS: TRUSTED,
    LAYER_PERSONALITY: TRUSTED,
    LAYER_RESPONSE_STYLE: TRUSTED,
    LAYER_PROFILE: TRUSTED,
    LAYER_PROJECT_INSTRUCTIONS: TRUSTED,
    LAYER_TASK_CONTEXT: TRUSTED,
    LAYER_SKILL_INSTRUCTIONS: UNTRUSTED,
    LAYER_RETRIEVED_CONTEXT: UNTRUSTED,
}

# Layers whose content is always treated as data, never as instructions.
UNTRUSTED_LAYERS: frozenset[str] = frozenset(
    {LAYER_SKILL_INSTRUCTIONS, LAYER_RETRIEVED_CONTEXT}
)

# Layers that cannot be replaced by a caller override.
NON_OVERRIDABLE_LAYERS: frozenset[str] = frozenset({LAYER_SYSTEM_POLICY})

# -- Size budgets (characters of layer content) ------------------------------

DEFAULT_LAYER_BUDGETS: dict[str, int] = {
    LAYER_SYSTEM_POLICY: 2000,
    LAYER_SYSTEM_INSTRUCTIONS: 4000,
    LAYER_PERSONALITY: 1500,
    LAYER_RESPONSE_STYLE: 1500,
    LAYER_PROFILE: 500,
    LAYER_PROJECT_INSTRUCTIONS: 2000,
    LAYER_TASK_CONTEXT: 2000,
    LAYER_SKILL_INSTRUCTIONS: 3000,
    LAYER_RETRIEVED_CONTEXT: 4000,
}

DEFAULT_TOTAL_BUDGET = 12000

TRUNCATION_MARKER = "\n[...truncated...]"

# Envelope markers use the ``<<<`` sigil. Any occurrence of that sigil inside
# layer content or a source label is escaped so content cannot forge a
# layer/envelope boundary.
_MARKER_SIGIL = "<<<"
_MARKER_ESCAPE = "< <<"

# A source label is rendered inside a header, so it must not contain anything
# that could terminate the header (``>``), forge a marker (``<``), introduce a
# newline, or inject a ``key=value`` pair.
_LABEL_DISALLOWED = re.compile(r"[^A-Za-z0-9._:/~-]")


def _neutralize(text: str) -> str:
    """Escape control markers so *text* cannot forge a layer/envelope boundary.

    Replaces every ``<<<`` occurrence with ``"< <<"``. A single pass is not
    enough: a run of four or more ``<`` can re-create the sigil (``"<<<<"`` ->
    ``"< <<<"``), so the replacement repeats until no sigil is left.

    Termination: within a run of ``n >= 3`` consecutive ``<`` one replacement
    turns it into runs ``1`` and ``n - 1``. So the potential
    ``phi = sum(max(0, run_length - 2))`` drops by exactly 1 per replacement and
    is 0 only when no ``<<<`` remains; ``phi`` is a non-negative integer, hence
    the loop ends after at most ``phi`` passes (e.g. 58 passes for 60 ``<``).
    """
    while _MARKER_SIGIL in text:
        text = text.replace(_MARKER_SIGIL, _MARKER_ESCAPE)
    return text


def _sanitize_label(source: str) -> str:
    """Reduce a source label to a safe token.

    Only ``[A-Za-z0-9._:/~-]`` survive; every other character (whitespace,
    ``<``, ``>``, ``=``, ``\r``/``\n``) becomes ``_``. A hostile document name
    therefore cannot close the header early (``>>>``), forge a marker (``<<<``),
    or inject a ``key=value`` pair such as ``id=system_policy trust=trusted``
    into the header it is embedded in.
    """
    return _LABEL_DISALLOWED.sub("_", str(source))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PromptLayer:
    """A single composed layer with provenance and budget state."""

    layer_id: str
    source: str
    trust: str
    content: str
    order: int
    truncated: bool = False
    dropped: bool = False


@dataclass
class PromptComposition:
    """Result of composing a prompt: layers plus the rendered text."""

    layers: tuple[PromptLayer, ...]
    text: str
    total_chars: int
    truncated: bool = False
    dropped: tuple[str, ...] = field(default_factory=tuple)

    def inspect(self) -> list[dict[str, Any]]:
        """Metadata-only view of the active layers (no content, no secrets)."""
        return [
            {
                "layer_id": layer.layer_id,
                "source": sanitize_text(layer.source),
                "trust": layer.trust,
                "order": layer.order,
                "chars": len(layer.content),
                "truncated": layer.truncated,
                "dropped": layer.dropped,
            }
            for layer in self.layers
        ]

    def preview(self, *, redact: bool = True) -> str:
        """Rendered text for user inspection; secret-like patterns are redacted."""
        return sanitize_text(self.text) if redact else self.text


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


class PromptComposer:
    """Deterministic composer for the layered instruction prompt."""

    def __init__(
        self,
        identity: Identity,
        *,
        total_budget: int = DEFAULT_TOTAL_BUDGET,
        layer_budgets: Mapping[str, int] | None = None,
    ) -> None:
        self.identity = identity
        self.total_budget = total_budget
        self.layer_budgets: dict[str, int] = {**DEFAULT_LAYER_BUDGETS, **(layer_budgets or {})}

    # -- Public API ----------------------------------------------------------

    def compose(
        self,
        *,
        project_instructions: str = "",
        task_context: str = "",
        skill_instructions: str = "",
        retrieved_documents: Sequence[tuple[str, str]] | None = None,
        overrides: Mapping[str, str] | None = None,
    ) -> PromptComposition:
        """Compose the prompt from identity + optional context.

        Args:
            project_instructions: project-scoped instructions (§16).
            task_context: current task/goal framing.
            skill_instructions: text supplied by a Skill (untrusted).
            retrieved_documents: ``(source, text)`` pairs (untrusted), order kept.
            overrides: explicit ``layer_id -> content`` replacements. Rejected
                for non-overridable layers (``system_policy``).

        Returns:
            A ``PromptComposition`` whose ``text`` is deterministic.
        """
        overrides = dict(overrides or {})
        self._validate_overrides(overrides)

        entries = self._collect_entries(
            overrides, project_instructions, task_context, skill_instructions, retrieved_documents
        )
        layers = self._apply_budgets(entries)
        text = self._render(layers)
        total_chars = sum(len(layer.content) for layer in layers)
        dropped = tuple(dict.fromkeys(layer.layer_id for layer in layers if layer.dropped))
        truncated = any(layer.truncated for layer in layers)
        return PromptComposition(
            layers=tuple(layers),
            text=text,
            total_chars=total_chars,
            truncated=truncated,
            dropped=dropped,
        )

    # -- Internals -----------------------------------------------------------

    @staticmethod
    def _validate_overrides(overrides: Mapping[str, str]) -> None:
        for layer_id in overrides:
            if layer_id not in LAYER_ORDER:
                raise SeraphimError(
                    code=ErrorCode.VALIDATION_FAILED,
                    component=COMPONENT,
                    safe_message=f"Unknown prompt layer in override: {layer_id!r}",
                    details={"layer_id": layer_id},
                )
            if layer_id in NON_OVERRIDABLE_LAYERS:
                raise SeraphimError(
                    code=ErrorCode.CONFIG_CONFLICT_DETECTED,
                    component=COMPONENT,
                    safe_message=(
                        f"Cannot override protected prompt layer '{layer_id}'. "
                        "It is controlled by system policy."
                    ),
                    details={"layer_id": layer_id},
                )
            if layer_id == LAYER_RETRIEVED_CONTEXT:
                raise SeraphimError(
                    code=ErrorCode.VALIDATION_FAILED,
                    component=COMPONENT,
                    safe_message=(
                        "retrieved_context cannot be overridden; pass untrusted text via "
                        "the retrieved_documents argument instead."
                    ),
                    details={"layer_id": layer_id},
                )

    def _collect_entries(
        self,
        overrides: dict[str, str],
        project_instructions: str,
        task_context: str,
        skill_instructions: str,
        retrieved_documents: Sequence[tuple[str, str]] | None,
    ) -> list[tuple[str, str, str, str]]:
        identity = self.identity
        base: dict[str, str] = {
            LAYER_SYSTEM_POLICY: SYSTEM_POLICY,
            LAYER_SYSTEM_INSTRUCTIONS: identity.system_instructions,
            LAYER_PERSONALITY: identity.personality,
            LAYER_RESPONSE_STYLE: identity.response_style,
            LAYER_PROFILE: _render_profile(identity.profile),
        }
        dynamic: dict[str, str] = {
            LAYER_PROJECT_INSTRUCTIONS: project_instructions,
            LAYER_TASK_CONTEXT: task_context,
            LAYER_SKILL_INSTRUCTIONS: skill_instructions,
        }

        entries: list[tuple[str, str, str, str]] = []
        for layer_id in LAYER_ORDER:
            if layer_id == LAYER_RETRIEVED_CONTEXT:
                continue  # appended below, after skill instructions
            overridden = layer_id in overrides
            if overridden:
                content = overrides[layer_id]
            elif layer_id in dynamic:
                content = dynamic[layer_id]
            else:
                content = base[layer_id]
            if not content:
                continue
            source = "override" if overridden else self._source_for(layer_id)
            entries.append((layer_id, source, TRUST_BY_LAYER[layer_id], content))

        for source, text in retrieved_documents or ():
            if not text:
                continue
            entries.append((LAYER_RETRIEVED_CONTEXT, source, UNTRUSTED, text))

        return entries

    def _source_for(self, layer_id: str) -> str:
        if layer_id == LAYER_SYSTEM_POLICY:
            return "builtin:system_policy"
        if layer_id == LAYER_PROJECT_INSTRUCTIONS:
            return "project"
        if layer_id == LAYER_TASK_CONTEXT:
            return "task"
        if layer_id == LAYER_SKILL_INSTRUCTIONS:
            return "skill"
        return self.identity.sources.get(layer_id, "builtin")

    def _apply_budgets(self, entries: list[tuple[str, str, str, str]]) -> list[PromptLayer]:
        remaining = self.total_budget
        layers: list[PromptLayer] = []
        for order, (layer_id, source, trust, content) in enumerate(entries):
            neutral = _neutralize(content)
            layer_budget = self.layer_budgets.get(layer_id, self.total_budget)
            truncated = False
            dropped = False

            # The cap applies to the retained content; ``TRUNCATION_MARKER`` is
            # an out-of-band annotation appended after it, so truncation stays
            # visible even for very small budgets.
            if layer_id in NON_OVERRIDABLE_LAYERS:
                # Protected layers are never dropped, but they still honor their
                # own per-layer budget (a soft limit: the total budget is not
                # allowed to evict system policy).
                if len(neutral) > layer_budget:
                    neutral = neutral[:layer_budget] + TRUNCATION_MARKER
                    truncated = True
            elif remaining <= 0:
                dropped = True
                neutral = ""
            else:
                cap = min(layer_budget, remaining)
                if len(neutral) > cap:
                    neutral = neutral[:cap] + TRUNCATION_MARKER
                    truncated = True

            remaining -= len(neutral)
            layers.append(
                PromptLayer(
                    layer_id=layer_id,
                    source=_sanitize_label(source),
                    trust=trust,
                    content=neutral,
                    order=order,
                    truncated=truncated,
                    dropped=dropped,
                )
            )
        return layers

    @staticmethod
    def _render(layers: list[PromptLayer]) -> str:
        blocks = [_render_block(layer) for layer in layers if layer.content and not layer.dropped]
        return "\n\n".join(blocks)


def _render_block(layer: PromptLayer) -> str:
    # Layer content is already neutralized in ``_apply_budgets``; the label is
    # sanitized here as well, because this is the last point before the header
    # string is built from it.
    source = _sanitize_label(layer.source)
    header = f"<<<LAYER id={layer.layer_id} source={source} trust={layer.trust}>>>"
    if layer.trust == UNTRUSTED:
        begin = f"<<<BEGIN_UNTRUSTED_DATA id={layer.layer_id} source={source}>>>"
        end = f"<<<END_UNTRUSTED_DATA id={layer.layer_id}>>>"
        return f"{header}\n{begin}\n{layer.content}\n{end}"
    return f"{header}\n{layer.content}"


def _render_profile(profile: Any) -> str:
    """Render profile settings as deterministic ``key: value`` lines."""
    return "\n".join(
        [
            f"display_name: {profile.display_name}",
            f"ui_language: {profile.ui_language}",
            f"response_language: {profile.response_language}",
            f"default_task_mode: {profile.default_task_mode}",
            f"timezone: {profile.timezone}",
        ]
    )
