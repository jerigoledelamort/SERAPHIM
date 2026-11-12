# SERAPHIM MODEL LAYER — privacy gate for outbound model traffic (S12-S14 review, D2).
#
# Spec §4.5: the privacy policy, not the model choice, decides what may leave the
# machine ("Передача данных наружу определяется privacy policy").
# CONTRACTS.md §6.4 puts the check *before* an external
# transmission, and TB-9 makes it the user's decision, not the provider's.
# SANCTUM already owns the deterministic policy (``sanctum.privacy``); this module
# is the thin seam that lets a provider ask that policy before a byte leaves the
# process.  MODEL LAYER may depend on SANCTUM (CONTRACTS.md §3.2 rule 7), so the
# gate is called here rather than pushed up into a provider-specific layer.
#
# Two rules make the gate usable without becoming a second policy engine:
#
# * it never decides anything itself — it builds a :class:`TransmissionRequest`
#   and asks ``sanctum.privacy``;
# * a request whose endpoint cannot carry data outward (a loopback server, an
#   in-process fake) is reported as *local*, which is the honest category for it:
#   no user data leaves the machine, so a policy that denies external
#   transmission must not block a local model.
#
# The default policy is deny-by-default (``PrivacyPolicy()`` denies external
# transmission), so a provider built without an explicit policy can only reach a
# local endpoint.  Wiring an operator-approved policy is the composition root's
# job (CORE/COMPASS), not the adapter's.

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlsplit

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.model_layer.content import Role, ToolResultPart
from seraphim.model_layer.request import ModelRequest
from seraphim.sanctum.privacy import (
    COMPONENT,
    PrivacyDecision,
    PrivacyPolicy,
    TransmissionRequest,
    evaluate_transmission,
)

__all__ = [
    "categories_for_request",
    "decide_health_transmission",
    "decide_transmission",
    "describe_privacy",
    "endpoint_is_local",
    "enforce_transmission",
    "transmission_request",
]


def endpoint_is_local(endpoint: str) -> bool:
    """Whether *endpoint* addresses this machine, so nothing leaves it.

    Only a loopback host counts as local.  A private/LAN address is *not* local:
    the data leaves this process and this machine, so the privacy policy has to
    decide it like any other external destination.
    """
    host = (urlsplit(endpoint).hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost":
        return True
    # A bracketed IPv6 literal arrives without brackets from ``hostname``.
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback


def categories_for_request(request: ModelRequest) -> tuple[str, ...]:
    """Map a normalized request onto SANCTUM's data categories.

    The mapping is deliberately conservative and stable: the categories describe
    *what kind of local context* the endpoint would receive, which is what the
    privacy summary shows the user.  Sorted output keeps the decision
    reproducible for the same request.
    """
    categories: set[str] = set()
    for message in request.messages:
        if message.role == Role.SYSTEM:
            categories.add("prompt")
        else:
            categories.add("conversation")
        if message.images():
            categories.add("images")
        if any(isinstance(part, ToolResultPart) for part in message.content):
            categories.add("tool_output")
    if not categories:
        categories.add("conversation")
    return tuple(sorted(categories))


def transmission_request(
    provider_id: str,
    request: ModelRequest,
    *,
    model: str,
    purpose: str,
    external: bool,
) -> TransmissionRequest:
    """Build the SANCTUM request for one model call.

    ``model`` is the model that would receive the context, ``purpose`` why
    (``chat``, ``stream``, ``health``): a health probe sends the credential and
    nothing else, and the policy still has to see it as a distinct purpose.
    """
    return TransmissionRequest(
        provider=provider_id or "model_layer",
        categories=categories_for_request(request),
        model=model,
        purpose=purpose,
        external=external,
    )


def decide_transmission(
    policy: PrivacyPolicy | None,
    provider_id: str,
    request: ModelRequest,
    *,
    model: str,
    purpose: str = "chat",
    external: bool = True,
) -> PrivacyDecision:
    """Evaluate the privacy policy for one model call without raising.

    ``policy=None`` means "no policy was wired", which resolves to the
    deny-by-default :class:`PrivacyPolicy` rather than to an unguarded path: an
    adapter that was never given a policy still cannot leak context outward.
    The caller records the decision first, then passes it to
    :func:`enforce_transmission`.
    """
    return evaluate_transmission(
        policy if policy is not None else PrivacyPolicy(),
        transmission_request(
            provider_id, request, model=model, purpose=purpose, external=external
        ),
    )


def decide_health_transmission(
    policy: PrivacyPolicy | None, provider_id: str, *, model: str, external: bool
) -> PrivacyDecision:
    """Evaluate the policy for a health/capability probe without raising.

    A probe sends the credential and a bare ``GET``: it has no request context to
    classify, but it still reaches an external host, so it must not bypass the
    policy.  The category set is empty, which the policy reads as "nothing of the
    user's would be sent" — and an external destination is still denied by
    default.
    """
    return evaluate_transmission(
        policy if policy is not None else PrivacyPolicy(),
        TransmissionRequest(
            provider=provider_id or "model_layer",
            categories=(),
            model=model,
            purpose="health",
            external=external,
        ),
    )


def enforce_transmission(decision: PrivacyDecision) -> PrivacyDecision:
    """Raise ``PRIVACY_TRANSMISSION_DENIED`` when *decision* denies the transfer."""
    if not decision.allowed:
        raise SeraphimError(
            code=ErrorCode.PRIVACY_TRANSMISSION_DENIED,
            component=COMPONENT,
            safe_message=decision.detail,
            user_action_required=True,
            details={
                "provider": decision.summary["provider"],
                "reason": decision.reason,
                "categories": [c["id"] for c in decision.summary["data_categories"]],
            },
        )
    return decision


def describe_privacy(policy: PrivacyPolicy | None) -> dict[str, Any]:
    """The policy view a UI/COMPASS can show before a call is made (spec §4.5)."""
    return (policy if policy is not None else PrivacyPolicy()).to_dict()
