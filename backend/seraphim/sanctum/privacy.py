# SERAPHIM SANCTUM — privacy policy gate (S09).
#
# Spec §4.5: "Для каждого провайдера UI показывает, какой контекст ему будет
# передан." Outbound transfer is decided by the privacy policy, not by the model
# choice alone.  TB-9: user data → outward is decided by policy and the user's
# choice.  §4.3: AEGIS decides before each action, including publication.
#
# This module is the deterministic decision point *before* any context leaves the
# machine.  It answers two questions:
#   1. What exactly would be sent, and to whom?  (:func:`summarize_request`)
#   2. Is that allowed by the current policy, and does it need a user ack?
#      (:func:`evaluate_transmission` / :func:`assert_transmission_allowed`)
#
# There are no silent uploads: the default policy denies external transmission,
# and an allowed decision still reports ``requires_confirmation`` when the policy
# asks for an explicit user confirmation.
#
# Wiring: MODEL LAYER (S12+) must call :func:`assert_transmission_allowed` before
# issuing a request to an external provider.  Until that call exists there is no
# outbound model traffic in the runtime.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import redact_known_secrets, sanitize_text

COMPONENT = "sanctum.privacy"

# ---------------------------------------------------------------------------
# Local data categories
# ---------------------------------------------------------------------------

#: Categories of local data that a provider request may carry.  The IDs are the
#: stable contract; descriptions are shown to the user in the privacy summary.
DATA_CATEGORIES: dict[str, str] = {
    "prompt": "System instructions, identity and task context",
    "conversation": "Session messages and previous turns",
    "files": "Contents of workspace files read for the task",
    "memory": "User and project memory records",
    "artifacts": "Generated artifacts (documents, code, CAD)",
    "images": "Screenshots and images",
    "tool_output": "Results returned by tools and integrations",
}

#: Decision reason codes (stable, machine-readable).
REASON_LOCAL_PROVIDER = "local_provider"
REASON_LOCAL_ONLY = "local_only"
REASON_EXTERNAL_DISABLED = "external_transmission_disabled"
REASON_PROVIDER_NOT_ALLOWED = "provider_not_allowed"
REASON_ALLOWED = "allowed"


def _fail(code: str, message: str, *, details: dict[str, Any] | None = None) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        user_action_required=True,
        details=details,
    )


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrivacyPolicy:
    """Transmission policy derived from :class:`PrivacyConfig`."""

    allow_external_transmission: bool = False
    local_only: bool = False
    require_confirmation: bool = True
    allowed_providers: frozenset[str] = field(default_factory=frozenset)
    redact_before_transmission: bool = True

    @classmethod
    def from_config(cls, config: Any) -> PrivacyPolicy:
        """Build a policy from a ``PrivacyConfig`` (or any compatible object)."""
        providers = getattr(config, "allowed_providers", []) or []
        return cls(
            allow_external_transmission=bool(
                getattr(config, "allow_external_transmission", False)
            ),
            local_only=bool(getattr(config, "local_only", False)),
            require_confirmation=bool(getattr(config, "require_confirmation", True)),
            allowed_providers=frozenset(str(p) for p in providers),
            redact_before_transmission=bool(
                getattr(config, "redact_before_transmission", True)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_external_transmission": self.allow_external_transmission,
            "local_only": self.local_only,
            "require_confirmation": self.require_confirmation,
            "allowed_providers": sorted(self.allowed_providers),
            "redact_before_transmission": self.redact_before_transmission,
        }


# ---------------------------------------------------------------------------
# Request / decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TransmissionRequest:
    """A pending transfer of local context to a model provider."""

    provider: str
    categories: tuple[str, ...] = ()
    model: str = ""
    purpose: str = "chat"
    #: ``False`` for a local provider (no data leaves the machine).
    external: bool = True

    def __post_init__(self) -> None:
        if not self.provider:
            raise _fail(ErrorCode.VALIDATION_FAILED, "Transmission request needs a provider.")
        unknown = sorted(set(self.categories) - set(DATA_CATEGORIES))
        if unknown:
            raise _fail(
                ErrorCode.VALIDATION_FAILED,
                f"Unknown data category/categories: {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(DATA_CATEGORIES))}.",
                details={"unknown_categories": unknown},
            )


@dataclass(frozen=True)
class PrivacyDecision:
    """Deterministic outcome of evaluating a request against a policy."""

    allowed: bool
    reason: str
    detail: str
    summary: dict[str, Any]
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "detail": self.detail,
            "requires_confirmation": self.requires_confirmation,
            "summary": self.summary,
        }


def summarize_request(request: TransmissionRequest) -> dict[str, Any]:
    """The privacy summary shown to the user before anything is transmitted.

    Contains the provider, the destination kind (local/external) and the local
    data categories that would be sent — and never any of the data itself.
    """
    return {
        "provider": request.provider,
        "model": request.model,
        "purpose": request.purpose,
        "destination": "external" if request.external else "local",
        "data_categories": [
            {"id": category, "description": DATA_CATEGORIES[category]}
            for category in request.categories
        ],
        "total_categories": len(request.categories),
    }


def render_summary(summary: dict[str, Any]) -> str:
    """Human-readable rendering of a privacy summary (used by CLI/GUI)."""
    lines = [
        "Privacy summary",
        f"  provider:    {summary['provider']}",
        f"  model:       {summary.get('model') or '(default)'}",
        f"  purpose:     {summary.get('purpose', 'chat')}",
        f"  destination: {summary['destination']}",
        "  local data categories that would be sent:",
    ]
    categories = summary.get("data_categories") or []
    if not categories:
        lines.append("    (none)")
    else:
        for category in categories:
            lines.append(f"    - {category['id']}: {category['description']}")
    return "\n".join(lines)


def evaluate_transmission(
    policy: PrivacyPolicy, request: TransmissionRequest
) -> PrivacyDecision:
    """Decide whether *request* may proceed under *policy*.

    Checks are applied in a fixed order, so the same inputs always produce the
    same decision (and the same explanation):

    1. a local provider never sends data outward → allowed;
    2. ``local_only`` policy → denied;
    3. external transmission disabled → denied;
    4. provider not in the allow-list → denied;
    5. otherwise allowed (with confirmation if the policy requires it).
    """
    summary = summarize_request(request)

    if not request.external:
        return PrivacyDecision(
            allowed=True,
            reason=REASON_LOCAL_PROVIDER,
            detail=f"'{request.provider}' is a local provider; no data leaves the machine.",
            summary=summary,
            requires_confirmation=False,
        )

    if policy.local_only:
        return PrivacyDecision(
            allowed=False,
            reason=REASON_LOCAL_ONLY,
            detail="Privacy policy is set to local_only; external transmission is disabled.",
            summary=summary,
        )

    if not policy.allow_external_transmission:
        return PrivacyDecision(
            allowed=False,
            reason=REASON_EXTERNAL_DISABLED,
            detail=(
                "External transmission is disabled by privacy policy. "
                "Enable it explicitly in privacy.yaml (allow_external_transmission) "
                "and list the provider in allowed_providers."
            ),
            summary=summary,
        )

    if request.provider not in policy.allowed_providers:
        return PrivacyDecision(
            allowed=False,
            reason=REASON_PROVIDER_NOT_ALLOWED,
            detail=(
                f"Provider '{request.provider}' is not in the privacy allow-list "
                "(allowed_providers)."
            ),
            summary=summary,
        )

    return PrivacyDecision(
        allowed=True,
        reason=REASON_ALLOWED,
        detail=f"Allowed by privacy policy for provider '{request.provider}'.",
        summary=summary,
        requires_confirmation=policy.require_confirmation,
    )


def assert_transmission_allowed(
    policy: PrivacyPolicy, request: TransmissionRequest
) -> PrivacyDecision:
    """Gate for the model call path: raise unless the transfer is allowed.

    Returns the (allowed) decision so the caller can show the summary and honour
    ``requires_confirmation``.  A denied decision becomes a structured
    ``PRIVACY_TRANSMISSION_DENIED`` error carrying the same summary.
    """
    decision = evaluate_transmission(policy, request)
    if not decision.allowed:
        raise SeraphimError(
            code=ErrorCode.PRIVACY_TRANSMISSION_DENIED,
            component=COMPONENT,
            safe_message=decision.detail,
            user_action_required=True,
            details={
                "provider": request.provider,
                "reason": decision.reason,
                "categories": list(request.categories),
            },
        )
    return decision


def prepare_payload(
    payload: str,
    policy: PrivacyPolicy,
    *,
    known_secrets: Any = None,
) -> str:
    """Redact a payload before it is sent, when the policy requires it.

    Combines pattern scrubbing with exact removal of secrets known to the
    process, so a provider key that reached the context cannot be transmitted.
    """
    if not policy.redact_before_transmission:
        return payload
    return redact_known_secrets(sanitize_text(payload), known_secrets)
