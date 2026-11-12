# SERAPHIM MODEL LAYER — normalized provider errors (S12).
#
# Every provider failure is mapped onto a small, provider-independent set of
# kinds (CONTRACTS.md §2.5, spec §4.5).  A provider adapter must translate its
# native error into a ProviderError so that CORE/COMPASS never have to know a
# provider's wire format.  Credentials are never placed in the error: the
# envelope from ``SeraphimError`` sanitizes free text and details (TB-7).

from __future__ import annotations

from enum import StrEnum

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_text


class ProviderErrorKind(StrEnum):
    """Provider-independent failure kinds."""

    AUTH = "auth"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_REQUEST = "invalid_request"
    CANCELLED = "cancelled"
    RESPONSE_INVALID = "response_invalid"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"


#: Mapping from a normalized kind to the stable error code (CONTRACTS.md §7).
KIND_TO_CODE: dict[str, str] = {
    ProviderErrorKind.AUTH: ErrorCode.PROVIDER_AUTH_FAILED,
    ProviderErrorKind.UNAVAILABLE: ErrorCode.PROVIDER_UNAVAILABLE,
    ProviderErrorKind.TIMEOUT: ErrorCode.PROVIDER_TIMEOUT,
    ProviderErrorKind.RATE_LIMITED: ErrorCode.PROVIDER_RATE_LIMITED,
    ProviderErrorKind.INVALID_REQUEST: ErrorCode.PROVIDER_REQUEST_INVALID,
    ProviderErrorKind.CANCELLED: ErrorCode.PROVIDER_CANCELLED,
    ProviderErrorKind.RESPONSE_INVALID: ErrorCode.RESPONSE_FORMAT_INVALID,
    ProviderErrorKind.CAPABILITY_UNSUPPORTED: ErrorCode.PROVIDER_CAPABILITY_UNSUPPORTED,
}

#: Default ``(retryable, user_action_required)`` flags per kind.  These express
#: the recovery contract: CORE may retry a timeout, but must not retry a bad
#: request, and must ask the user to fix credentials/permissions.
KIND_DEFAULTS: dict[str, tuple[bool, bool]] = {
    ProviderErrorKind.AUTH: (False, True),
    ProviderErrorKind.UNAVAILABLE: (True, False),
    ProviderErrorKind.TIMEOUT: (True, False),
    ProviderErrorKind.RATE_LIMITED: (True, False),
    ProviderErrorKind.INVALID_REQUEST: (False, True),
    ProviderErrorKind.CANCELLED: (False, False),
    ProviderErrorKind.RESPONSE_INVALID: (True, False),
    ProviderErrorKind.CAPABILITY_UNSUPPORTED: (False, True),
}


class ProviderError(SeraphimError):
    """A provider failure normalized onto the shared error envelope.

    The error carries a provider-independent ``kind`` plus the stable ``code``.
    Provider adapters pass only a *safe* message; the base class scrubs secrets
    and stack traces, so an API key can never leak through an error.
    """

    def __init__(
        self,
        kind: str,
        provider_id: str = "",
        *,
        safe_message: str = "",
        retryable: bool | None = None,
        user_action_required: bool | None = None,
        details: dict | None = None,
        correlation_id: str = "",
        task_id: str = "",
    ) -> None:
        if kind not in KIND_TO_CODE:
            # Programming error, not a provider failure: fail loudly.
            msg = f"Unknown ProviderErrorKind: {kind!r}"
            raise ValueError(msg)
        default_retryable, default_action = KIND_DEFAULTS[kind]
        # ``provider_id`` ends up in the user-facing ``component`` field, which
        # the shared envelope does not sanitize — scrub it here so a value that
        # was pasted into provider_id by mistake cannot leak (TB-7).
        safe_provider_id = sanitize_text(provider_id)
        component = f"model_layer.{safe_provider_id}" if safe_provider_id else "model_layer"
        super().__init__(
            code=KIND_TO_CODE[kind],
            component=component,
            safe_message=safe_message,
            retryable=default_retryable if retryable is None else retryable,
            user_action_required=default_action if user_action_required is None else user_action_required,
            details=details,
            correlation_id=correlation_id,
            task_id=task_id,
        )
        self.kind = kind
        self.provider_id = safe_provider_id


# -- Convenience constructors (used by adapters and the fake provider) --------
#
# Each constructor accepts optional ``retryable`` / ``user_action_required`` /
# ``details`` overrides.  The per-kind defaults express the recovery contract;
# an adapter overrides them when it knows better (for example a size limit or a
# duplicate call id is deterministic, so retrying cannot help).


def provider_auth_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    """Authentication failed. Never includes the credential value."""
    return ProviderError(
        ProviderErrorKind.AUTH,
        provider_id,
        safe_message=safe_message or f"authentication failed for provider {provider_id!r}",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_timeout_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.TIMEOUT,
        provider_id,
        safe_message=safe_message or f"provider {provider_id!r} timed out",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_unavailable_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.UNAVAILABLE,
        provider_id,
        safe_message=safe_message or f"provider {provider_id!r} is unavailable",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_rate_limited_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.RATE_LIMITED,
        provider_id,
        safe_message=safe_message or f"provider {provider_id!r} rate limited the request",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_cancelled_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.CANCELLED,
        provider_id,
        safe_message=safe_message or f"provider {provider_id!r} request was cancelled",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_request_invalid_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.INVALID_REQUEST,
        provider_id,
        safe_message=safe_message or f"invalid request for provider {provider_id!r}",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def provider_capability_error(
    provider_id: str, feature: str, *, safe_message: str = ""
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.CAPABILITY_UNSUPPORTED,
        provider_id,
        safe_message=safe_message
        or f"provider {provider_id!r} does not support feature {feature!r}",
        details={"feature": feature},
    )


def provider_response_invalid_error(
    provider_id: str,
    *,
    safe_message: str = "",
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    details: dict | None = None,
) -> ProviderError:
    return ProviderError(
        ProviderErrorKind.RESPONSE_INVALID,
        provider_id,
        safe_message=safe_message or f"provider {provider_id!r} returned an invalid response",
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )
