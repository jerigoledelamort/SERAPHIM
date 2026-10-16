# SERAPHIM SANCTUM — secret-free export (S09).
#
# Spec §15: "Секреты по умолчанию не экспортировать."  Golden scenario §20.2 #18:
# "Экспортировать конфиг без секретов."  CONTRACTS.md §4.4: secrets are not in
# YAML config, logs or exports (by default).
#
# S09 provides the *guarantee*: a builder that produces a secret-free snapshot
# (only secret *references*, never values) and a verifier that fails loudly if
# any secret material is present.  The full export/import/backup pipeline
# (manifest, schema versions, restore checks) is S11 and reuses these functions.
#
# The verifier is deliberately strict: it checks both generic secret patterns and
# the exact values of secrets known to the process, and it reports only the JSON
# path where a leak was found — never the leaked value itself.

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import REDACTED, SecretRedactor, sanitize_dict, sanitize_value
from seraphim.sanctum.identity import load_identity
from seraphim.sanctum.loader import load_config
from seraphim.sanctum.secrets import SecretStore, create_secret_store

COMPONENT = "sanctum.export"

#: What replaces a secret value in an export: the logical reference, never the
#: value itself.  The reference is already a config field, so an export stays
#: restorable while carrying no secret material.
SECRET_REF_KEY = "secret_ref"

EXPORT_FORMAT_VERSION = 1


def _fail(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        user_action_required=True,
        details=details,
    )


def build_safe_export(
    root: str | os.PathLike[str],
    *,
    secret_store: SecretStore | None = None,
    user_identity_dir: Path | None = None,
    workspace_identity_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a configuration export that contains no secret values.

    Args:
        root: SERAPHIM root directory.
        secret_store: Store used to describe where secrets live.  Defaults to the
            platform store for *root*.
        user_identity_dir: Identity override passed through to ``load_identity``.
        workspace_identity_dir: Identity override passed through to ``load_identity``.

    Returns:
        A JSON-safe dict with ``config``, ``identity`` and a ``secrets`` section
        that lists references and the backend location, and states explicitly
        that values are excluded.
    """
    root_path = Path(root)
    store = secret_store if secret_store is not None else create_secret_store(root_path)
    config = load_config(root_path)
    identity = load_identity(
        root_path,
        user_identity_dir=user_identity_dir,
        workspace_identity_dir=workspace_identity_dir,
    )

    payload: dict[str, Any] = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "config": {
            "runtime": config.runtime.to_dict(),
            "providers": config.providers.to_dict(),
            "routing": config.routing.to_dict(),
            "mcp": config.mcp.to_dict(),
            "permissions": config.permissions.to_dict(),
            "privacy": config.privacy.to_dict(),
            "paths": config.paths.to_dict(),
            "ui": config.ui.to_dict(),
        },
        "identity": {
            "profile": asdict(identity.profile),
            "sources": dict(identity.sources),
            "system_instructions": identity.system_instructions,
            "personality": identity.personality,
            "response_style": identity.response_style,
        },
        "secrets": {
            "included": False,
            "backend": store.info.backend,
            # Logical location (relative to the root where possible) so an export
            # is portable and does not embed machine-specific absolute paths.
            "location": _logical_location(store.info.location, root_path),
            # Reference names only; the values are not read, so they cannot leak.
            "refs": store.list_refs(),
            "note": (
                "Secret values are never exported. A reference such as "
                "'provider.openai' is restored from the platform secret store; "
                "re-enter the value after an import if the store moved."
            ),
        },
    }
    payload = sanitize_export(payload)
    # Defence in depth: the export builder refuses to return a payload that its
    # own verifier flags.  Because ``sanitize_export`` already scrubbed patterns
    # and known values, a failure here means the sanitizer has a hole — which is
    # exactly when an export must not be produced.
    verify_no_secrets(payload)
    return payload


def _logical_location(location: str, root: Path) -> str:
    """Describe the store location relative to the root when it is inside it."""
    try:
        return Path(location).relative_to(root).as_posix()
    except (ValueError, OSError):
        return location


def sanitize_export(payload: Any) -> Any:
    """Deep-sanitize an export payload as defence in depth.

    Key-based rules plus a pattern scrub on every string value, so even a value
    that slipped into a field the schema does not know about is redacted.
    """
    return sanitize_dict(payload) if isinstance(payload, dict) else sanitize_value(payload)


def find_secret_material(
    payload: Any,
    *,
    known_secrets: str | list[str] | None = None,
) -> list[str]:
    """Return JSON paths in *payload* where secret material was detected.

    Detects both pattern-like secrets and the exact values of secrets known to
    the process (explicitly passed or registered by the secret store).  Keys are
    inspected as well as values.  The returned paths never contain the value.
    """
    redactor = SecretRedactor(known_secrets)
    leaks: list[str] = []
    _walk(payload, "$", redactor, leaks)
    return leaks


def _walk(node: Any, path: str, redactor: SecretRedactor, leaks: list[str]) -> None:
    if isinstance(node, str):
        if node != REDACTED and redactor.redact(node) != node:
            leaks.append(path)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and redactor.redact(key) != key:
                # The key itself is secret material: report the location without
                # echoing the offending key.
                leaks.append(f"{path}.*")
                child_path = f"{path}.*"
            else:
                child_path = f"{path}.{key}"
            _walk(value, child_path, redactor, leaks)
        return
    if isinstance(node, (list, tuple, set, frozenset)):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", redactor, leaks)


def verify_no_secrets(
    payload: Any,
    *,
    known_secrets: str | list[str] | None = None,
) -> None:
    """Fail if *payload* contains secret material.

    Raises:
        SeraphimError: ``DIAGNOSTIC_EXPORT_FAILED`` listing the offending paths.
            The secret value is never included in the message.
    """
    leaks = find_secret_material(payload, known_secrets=known_secrets)
    if leaks:
        raise _fail(
            ErrorCode.DIAGNOSTIC_EXPORT_FAILED,
            "Export contains secret material and was refused: "
            f"{', '.join(leaks[:5])}"
            + (f" (+{len(leaks) - 5} more)" if len(leaks) > 5 else ""),
            details={"paths": leaks[:20], "count": len(leaks)},
        )
