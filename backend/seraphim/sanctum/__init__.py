# SANCTUM — identity, configuration, instructions (S03 skeleton)

"""
SANCTUM — configuration & credential subsystem (S07-S09).

Provides:
- Versioned configuration schemas (runtime, providers, routing, MCP, permissions, privacy, paths, UI)
- 5-level priority configuration loading (System security > User > Workspace > Task > Defaults)
- Single validation entry point with detailed diagnostics
- Identity composition and a deterministic prompt composer (S08)
- Platform secret storage with fail-closed fallback, privacy gate and
  secret-free export (S09)
"""

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
from seraphim.sanctum.export import (
    build_safe_export,
    find_secret_material,
    verify_no_secrets,
)
from seraphim.sanctum.identity import (
    Identity,
    IdentityConfig,
    ProfileSettings,
    load_identity,
)
from seraphim.sanctum.loader import LoadedConfig, load_config
from seraphim.sanctum.privacy import (
    DATA_CATEGORIES,
    PrivacyDecision,
    PrivacyPolicy,
    TransmissionRequest,
    assert_transmission_allowed,
    evaluate_transmission,
    prepare_payload,
    render_summary,
    summarize_request,
)
from seraphim.sanctum.prompt_composer import (
    LAYER_ORDER,
    PromptComposer,
    PromptComposition,
    PromptLayer,
)
from seraphim.sanctum.secrets import (
    DPAPISecretStore,
    InMemorySecretStore,
    SecretStore,
    SecretStoreInfo,
    UnavailableSecretStore,
    create_secret_store,
    mask_secret,
    validate_secret_ref,
)
from seraphim.sanctum.validator import ValidationIssue, ValidationResult, validate_config_files

__all__ = [
    "DATA_CATEGORIES",
    "LAYER_ORDER",
    "DPAPISecretStore",
    "Identity",
    "IdentityConfig",
    "InMemorySecretStore",
    "LoadedConfig",
    "MCPConfig",
    "MCPServerEntry",
    "ModelEntry",
    "PathsConfig",
    "PermissionsConfig",
    "PrivacyConfig",
    "PrivacyDecision",
    "PrivacyPolicy",
    "ProfileSettings",
    "PromptComposer",
    "PromptComposition",
    "PromptLayer",
    "ProvidersConfig",
    "RoutingConfig",
    "RoutingRule",
    "RuntimeConfig",
    "SecretStore",
    "SecretStoreInfo",
    "TransmissionRequest",
    "UIConfig",
    "UnavailableSecretStore",
    "ValidationIssue",
    "ValidationResult",
    "assert_transmission_allowed",
    "build_safe_export",
    "create_secret_store",
    "evaluate_transmission",
    "find_secret_material",
    "load_config",
    "load_identity",
    "mask_secret",
    "prepare_payload",
    "render_summary",
    "summarize_request",
    "validate_config_files",
    "validate_secret_ref",
    "verify_no_secrets",
]
