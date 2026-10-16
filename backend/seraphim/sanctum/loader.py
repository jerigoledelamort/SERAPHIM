# SERAPHIM SANCTUM — configuration loader (S07).
# Unified configuration loading with 5-level priority (spec §12.3).
#
# Priority order (highest first):
#   1. System security overrides (non-overridable fields)
#   2. User-level config (~/.config/seraphim/)
#   3. Workspace/project-level config (<workspace>/.seraphim/)
#   4. Task-level overrides (runtime API)
#   5. Defaults (from schemas)
#
# Merge order is the reverse (defaults first, system security last).  Only the
# system security layer may change a protected field; user/workspace/task layers
# that try to change one are rejected with CONFIG_CONFLICT_DETECTED.
#
# Config files are YAML, human-readable, inside SERAPHIM root (§12.2).
# Validation errors indicate specific file/key and fix instructions (§12.4).

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, TypeVar

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.versioned import VersionedEntity
from seraphim.sanctum.config_schemas import (
    MCPConfig,
    MCPServerEntry,
    ModelEntry,
    PathsConfig,
    PermissionsConfig,
    PrivacyConfig,
    ProvidersConfig,
    RoutingConfig,
    RoutingRule,
    RuntimeConfig,
    UIConfig,
)
from seraphim.sanctum.secrets import looks_like_secret, validate_secret_ref

COMPONENT = "sanctum.loader"

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Config file locations (§12.2)
# ---------------------------------------------------------------------------

# System security config (read-only, shipped with installation).
_SYSTEM_SECURITY_FILE = "config/system_security.yaml"

# User-level config directory (~/.config/seraphim/).
_USER_CONFIG_DIR_NAME = ".config"
_SERAPHIM_USER_SUBDIR = "seraphim"

# Workspace-level config directory (<workspace>/.seraphim/).
_WORKSPACE_CONFIG_DIR = ".seraphim"

# Config domain → filename mapping.
_DOMAIN_FILES = {
    "runtime": "runtime.yaml",
    "providers": "providers.yaml",
    "routing": "routing.yaml",
    "mcp": "mcp.yaml",
    "permissions": "permissions.yaml",
    "privacy": "privacy.yaml",
    "paths": "paths.yaml",
    "ui": "ui.yaml",
}

# Schema class for each domain.
_DOMAIN_SCHEMAS = {
    "runtime": RuntimeConfig,
    "providers": ProvidersConfig,
    "routing": RoutingConfig,
    "mcp": MCPConfig,
    "permissions": PermissionsConfig,
    "privacy": PrivacyConfig,
    "paths": PathsConfig,
    "ui": UIConfig,
}

# Non-overridable fields (system security layer, cannot be changed by user/workspace).
_NON_OVERRIDABLE_FIELDS = {
    "permissions": {"allow_external_writes"},
    "privacy": {"redact_credentials"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fail(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    user_action_required: bool = True,
    details: dict[str, Any] | None = None,
) -> SeraphimError:
    return SeraphimError(
        code=code,
        component=COMPONENT,
        safe_message=message,
        retryable=retryable,
        user_action_required=user_action_required,
        details=details,
    )


def _safe_load_yaml(path: Path) -> dict[str, Any] | None:
    """
    Load YAML from path. Return None if file not found, raise on parse error.
    """
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            content = yaml.safe_load(f)
            if content is None:
                return {}
            if not isinstance(content, dict):
                raise _fail(
                    ErrorCode.CONFIG_SCHEMA_INVALID,
                    f"Config file must contain a YAML dictionary, got {type(content).__name__}",
                    details={"file": str(path)},
                )
            return content
    except yaml.YAMLError as exc:
        raise _fail(
            ErrorCode.CONFIG_SCHEMA_INVALID,
            f"Failed to parse YAML: {exc}",
            details={"file": str(path), "error": str(exc)},
        ) from exc


def _merge_dicts(base: dict[str, Any], override: dict[str, Any], *, protected_keys: set[str] | None = None) -> dict[str, Any]:
    """
    Merge override into base. Reject if override tries to change protected_keys.
    """
    protected_keys = protected_keys or set()
    result = base.copy()
    for key, value in override.items():
        if key in protected_keys and key in result and result[key] != value:
            raise _fail(
                ErrorCode.CONFIG_CONFLICT_DETECTED,
                f"Cannot override protected field '{key}'",
                details={"field": key, "base_value": result[key], "attempted_override": value},
            )
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value, protected_keys=protected_keys)
        else:
            result[key] = value
    return result


def _validate_no_unknown_critical_keys(data: dict[str, Any], schema_cls: type, file_path: str) -> None:
    """
    Ensure no unknown keys are present in data that are not defined in schema_cls fields.
    All unknown keys are treated as critical (no silent ignoring).
    """
    schema_fields = {f.name for f in fields(schema_cls)}
    # VersionedEntity adds _extra_fields, schema_version is always valid
    schema_fields.add("_extra_fields")
    unknown = set(data.keys()) - schema_fields
    if unknown:
        unknown_list = sorted(unknown)
        # Include unknown key-value pairs for debugging (will be sanitized by SeraphimError)
        unknown_data = {k: data[k] for k in unknown_list}
        raise _fail(
            ErrorCode.CONFIG_SCHEMA_INVALID,
            f"Unknown configuration keys in {file_path}: {', '.join(unknown_list)}. "
            f"Remove these keys or check schema version compatibility.",
            details={"file": file_path, "unknown_keys": unknown_list, "unknown_data": unknown_data},
        )


def _check_duplicate_ids(entries: list[Any], id_field: str, domain: str, file_path: str) -> None:
    """
    Check for duplicate IDs in a list of entries (models, routing rules, MCP servers).
    """
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            entry_id = entry.get(id_field, "")
        else:
            entry_id = getattr(entry, id_field, "")
        if entry_id in seen:
            raise _fail(
                ErrorCode.CONFIG_SCHEMA_INVALID,
                f"Duplicate {id_field} '{entry_id}' in {domain} config",
                details={"file": file_path, "duplicate_id": entry_id, "domain": domain},
            )
        seen.add(entry_id)


def _check_entry_keys(entries: list[Any], schema_cls: type, domain: str, file_path: str) -> None:
    """Reject unknown keys inside list entries (e.g. ``providers.models[]``).

    The top-level check does not recurse into list entries, so without this a
    key such as ``credential_ref`` or ``api_key`` inside a model entry would be
    accepted silently — exactly the place a raw key would end up (spec §4.5).
    """
    allowed = {f.name for f in fields(schema_cls)}
    allowed.add("_extra_fields")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        unknown = sorted(set(entry.keys()) - allowed)
        if unknown:
            raise _fail(
                ErrorCode.CONFIG_SCHEMA_INVALID,
                f"Unknown keys in {domain} entry #{index}: {', '.join(unknown)}. "
                f"Remove these keys or check schema version compatibility.",
                details={"file": file_path, "unknown_keys": unknown, "entry_index": index},
            )


def _check_secret_refs(models: list[Any], file_path: str) -> None:
    """Reject literal secrets in config and malformed ``secret_ref`` values.

    Spec §4.5 / CONTRACTS §4.4: an API key is never stored in a config file.
    A ``secret_ref`` is a logical name; if the value looks like a real key the
    user pasted it in the wrong place, so the config is rejected instead of
    being accepted and later written to logs or exports.

    The offending value is never echoed back into the error message.
    """
    for index, entry in enumerate(models):
        if isinstance(entry, dict):
            ref = entry.get("secret_ref", "")
            model_id = entry.get("id", f"#{index}")
        else:
            ref = getattr(entry, "secret_ref", "")
            model_id = getattr(entry, "id", f"#{index}")
        if not ref:
            continue
        if looks_like_secret(ref):
            raise _fail(
                ErrorCode.SECRET_REF_INVALID,
                f"providers.models[{model_id}].secret_ref looks like a literal API key. "
                f"Store the value with 'seraphim secrets set <ref>' and put only the "
                f"reference name in the config.",
                user_action_required=True,
                details={"file": file_path, "key": "secret_ref", "model_id": model_id},
            )
        try:
            validate_secret_ref(ref)
        except SeraphimError as exc:
            raise _fail(
                ErrorCode.SECRET_REF_INVALID,
                f"providers.models[{model_id}].secret_ref is invalid: {exc.safe_message}",
                user_action_required=True,
                details={"file": file_path, "key": "secret_ref", "model_id": model_id},
            ) from exc


def _check_mcp_credentials(servers: list[Any], file_path: str) -> None:
    """Reject literal secrets in MCP server launch settings.

    ``mcp.servers[].env`` and ``command`` are the remaining config fields that
    naturally carry credentials (a GitHub token, a provider key).  A value that
    looks like a real key is rejected rather than written to a config file,
    logged or exported.  The offending value is never echoed back.

    Injecting a credential into an MCP server from the secret store is a later
    stage (S37); until then a literal key here is a configuration error.
    """
    for index, entry in enumerate(servers):
        if not isinstance(entry, dict):
            continue
        server_id = entry.get("id", f"#{index}")
        candidates: list[tuple[str, Any]] = []
        env = entry.get("env")
        if isinstance(env, dict):
            candidates.extend((f"env.{name}", value) for name, value in env.items())
        command = entry.get("command")
        if isinstance(command, list):
            candidates.extend((f"command[{i}]", value) for i, value in enumerate(command))
        for field_name, value in candidates:
            if isinstance(value, str) and looks_like_secret(value):
                raise _fail(
                    ErrorCode.SECRET_REF_INVALID,
                    f"mcp.servers[{server_id}].{field_name} looks like a literal "
                    f"secret. Store the value with 'seraphim secrets set <ref>' and "
                    f"reference it instead of pasting it into the config.",
                    user_action_required=True,
                    details={
                        "file": file_path,
                        "key": f"mcp.servers[].{field_name}",
                        "server_id": str(server_id),
                    },
                )


# ---------------------------------------------------------------------------
# Loading logic
# ---------------------------------------------------------------------------


def _load_config_for_domain(
    domain: str,
    root: Path,
    *,
    system_security_path: Path | None = None,
    user_config_path: Path | None = None,
    workspace_config_path: Path | None = None,
    task_overrides: dict[str, Any] | None = None,
) -> VersionedEntity:
    """
    Load config for a single domain with 5-level priority (spec §12.3).

    Layers are merged from lowest to highest authority, so a later merge wins:

        Defaults → Task → Workspace → User → System security

    ``System security`` is applied last because it is the only layer allowed to
    set a protected (non-overridable) field; every lower layer is merged through
    :func:`_merge_dicts` with ``_NON_OVERRIDABLE_FIELDS`` for the domain, so an
    attempt to weaken a protected field raises ``CONFIG_CONFLICT_DETECTED``
    instead of being accepted silently.

    Returns an instance of the appropriate config schema.
    """
    schema_cls = _DOMAIN_SCHEMAS[domain]
    filename = _DOMAIN_FILES[domain]

    # Fields that no user/workspace/task layer may change (system security only).
    protected_keys = _NON_OVERRIDABLE_FIELDS.get(domain, set())

    # Level 5: Defaults (lowest priority)
    merged = asdict(schema_cls())

    # Level 4: Task overrides (runtime API; cannot touch protected fields)
    if task_overrides:
        merged = _merge_dicts(merged, task_overrides, protected_keys=protected_keys)

    # Level 3: Workspace/project config (cannot touch protected fields)
    if workspace_config_path:
        workspace_file = workspace_config_path / filename
        workspace_data = _safe_load_yaml(workspace_file)
        if workspace_data:
            _validate_no_unknown_critical_keys(workspace_data, schema_cls, str(workspace_file))
            merged = _merge_dicts(merged, workspace_data, protected_keys=protected_keys)

    # Level 2: User config (cannot touch protected fields)
    if user_config_path:
        user_file = user_config_path / filename
        user_data = _safe_load_yaml(user_file)
        if user_data:
            _validate_no_unknown_critical_keys(user_data, schema_cls, str(user_file))
            merged = _merge_dicts(merged, user_data, protected_keys=protected_keys)

    # Level 1: System security (highest priority; may set protected fields)
    if system_security_path:
        system_file = system_security_path / filename
        system_data = _safe_load_yaml(system_file)
        if system_data:
            _validate_no_unknown_critical_keys(system_data, schema_cls, str(system_file))
            # System security is the authority for protected fields, so it is
            # applied last and may override anything set by lower layers.
            for key, value in system_data.items():
                merged[key] = value

    # Validate ID uniqueness for list-based configs
    if domain == "providers" and "models" in merged:
        _check_entry_keys(merged["models"], ModelEntry, "providers.models", "providers.yaml")
        _check_duplicate_ids(merged["models"], "id", "providers", "merged config")
        _check_secret_refs(merged["models"], "providers.yaml")
    if domain == "routing" and "rules" in merged:
        _check_entry_keys(merged["rules"], RoutingRule, "routing.rules", "routing.yaml")
        _check_duplicate_ids(merged["rules"], "id", "routing", "merged config")
    if domain == "mcp" and "servers" in merged:
        _check_entry_keys(merged["servers"], MCPServerEntry, "mcp.servers", "mcp.yaml")
        _check_duplicate_ids(merged["servers"], "id", "mcp", "merged config")
        _check_mcp_credentials(merged["servers"], "mcp.yaml")

    # Deserialize into schema instance (triggers VersionedEntity validation)
    try:
        return schema_cls.from_dict(merged)
    except Exception as exc:
        raise _fail(
            ErrorCode.CONFIG_SCHEMA_INVALID,
            f"Failed to load {domain} config: {exc}",
            details={"domain": domain, "error": str(exc)},
        ) from exc


@dataclass
class LoadedConfig:
    """Container for all loaded configuration domains."""

    runtime: RuntimeConfig
    providers: ProvidersConfig
    routing: RoutingConfig
    mcp: MCPConfig
    permissions: PermissionsConfig
    privacy: PrivacyConfig
    paths: PathsConfig
    ui: UIConfig


def load_config(
    root: Path,
    *,
    task_overrides: dict[str, dict[str, Any]] | None = None,
) -> LoadedConfig:
    """
    Load all configuration domains with 5-level priority.

    Args:
        root: SERAPHIM root directory
        task_overrides: Optional dict mapping domain name → override dict

    Returns:
        LoadedConfig with all domains loaded and validated

    Raises:
        SeraphimError: if any config file is malformed, has unknown keys,
                       duplicate IDs, or conflicts with non-overridable fields
    """
    # Locate config directories
    system_security_path = root / "config"

    user_home = Path.home()
    user_config_path = user_home / _USER_CONFIG_DIR_NAME / _SERAPHIM_USER_SUBDIR

    workspace_config_path = root / _WORKSPACE_CONFIG_DIR

    # Load each domain
    task_overrides = task_overrides or {}

    runtime = _load_config_for_domain(
        "runtime",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("runtime"),
    )
    providers = _load_config_for_domain(
        "providers",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("providers"),
    )
    routing = _load_config_for_domain(
        "routing",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("routing"),
    )
    mcp = _load_config_for_domain(
        "mcp",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("mcp"),
    )
    permissions = _load_config_for_domain(
        "permissions",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("permissions"),
    )
    privacy = _load_config_for_domain(
        "privacy",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("privacy"),
    )
    paths = _load_config_for_domain(
        "paths",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("paths"),
    )
    ui = _load_config_for_domain(
        "ui",
        root,
        system_security_path=system_security_path,
        user_config_path=user_config_path,
        workspace_config_path=workspace_config_path,
        task_overrides=task_overrides.get("ui"),
    )

    return LoadedConfig(
        runtime=runtime,
        providers=providers,
        routing=routing,
        mcp=mcp,
        permissions=permissions,
        privacy=privacy,
        paths=paths,
        ui=ui,
    )
