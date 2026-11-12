# SERAPHIM SANCTUM — configuration schemas (S07).
# Versioned dataclasses for each config domain per spec §12.2.
#
# Schema versions follow CONTRACTS.md §6.1:
#   - Minor (compatible): add optional field. Preserve unknown fields round-trip.
#   - Major (incompatible): remove/change/add required field. New version.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seraphim.contracts.versioned import VersionedEntity

# ---------------------------------------------------------------------------
# Runtime Configuration (§12.2 — runtime/behavior controls)
# ---------------------------------------------------------------------------

@dataclass
class RuntimeConfig(VersionedEntity):
    """Runtime behavior configuration."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    # Max depth for autonomous planning trees before forced user confirmation.
    max_autonomous_depth: int = 3
    # Parallel tool execution limit.
    max_parallel_tools: int = 5
    # Recovery attempt limit per task.
    max_recovery_attempts: int = 3
    # Enable anti-loop detection in CORE.
    enable_anti_loop: bool = True
    # Task inactivity timeout (seconds; 0 = no timeout).
    task_timeout_sec: int = 600


# ---------------------------------------------------------------------------
# Providers / Models Configuration (§12.2)
# ---------------------------------------------------------------------------

@dataclass
class ModelEntry:
    """Single model provider entry.

    Transport fields (S13) describe how to reach an HTTP endpoint; they are all
    optional with conservative defaults, so a config written before S13 keeps
    working unchanged (CONTRACTS.md §6.1 — adding an optional field is minor).
    Nothing here selects an endpoint or a feature in source: an endpoint, its
    paths, its auth scheme and its capabilities are *configuration*.
    """

    id: str
    provider: str  # "anthropic", "openai", "local_ollama", etc.
    model_name: str
    endpoint: str = ""
    # Logical reference to a value held in the platform secret store.  The
    # config never contains the credential itself (spec §4.5, CONTRACTS §4.4).
    secret_ref: str = ""
    # Max tokens for this model.
    max_tokens: int = 4096
    # Cost metadata (cost_per_million_tokens_in, cost_per_million_tokens_out).
    cost_input: float = 0.0
    cost_output: float = 0.0

    # --- HTTP transport (S13) -------------------------------------------------
    # Per-request timeout in seconds.
    timeout_seconds: float = 30.0
    # Path appended to ``endpoint`` for a chat completion request.
    chat_path: str = "/v1/chat/completions"
    # Path appended to ``endpoint`` for the health/capability probe.
    health_path: str = "/v1/models"
    # How the credential is presented: "bearer" (Authorization: Bearer <key>),
    # "api_key" (raw value in ``auth_header``, e.g. Azure ``api-key``) or "none".
    auth_scheme: str = "bearer"
    # Header name used to carry the credential.
    auth_header: str = "Authorization"
    # Extra non-secret headers sent with every request.  A value that looks like
    # a literal credential is rejected by the loader — this field is not a place
    # to paste an API key.
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Name of the request field that carries the output-token budget.  Most
    # OpenAI-compatible servers use "max_tokens"; newer OpenAI models use
    # "max_completion_tokens"; an empty string omits the field entirely.
    max_tokens_field: str = "max_tokens"
    # Explicit capability declaration for this endpoint.  Capabilities are never
    # inferred from the model name; an empty map means "chat only".
    capabilities: dict[str, Any] = field(default_factory=dict)

    # --- Streaming (S14) ------------------------------------------------------
    # Caps enforced while consuming a streamed response.  They are optional with
    # conservative defaults, so a config written before S14 keeps working; a
    # declared value must be positive (there is no "0 disables" escape hatch).
    # Total bytes of one streamed response body.
    stream_max_response_bytes: int = 8_000_000
    # Bytes of one accumulated SSE event.
    stream_max_event_bytes: int = 1_000_000
    # Assembled JSON arguments of one streamed tool call, in bytes.
    stream_max_arguments_bytes: int = 1_000_000
    # Maximum number of streamed tool calls in one response.
    stream_max_tool_calls: int = 64
    # Longest silence between two stream chunks before the stream is abandoned.
    stream_idle_timeout_seconds: float = 120.0
    # Ask the endpoint to include a usage object in the stream
    # (OpenAI ``stream_options.include_usage``).  Off by default.
    stream_include_usage: bool = False


@dataclass
class ProvidersConfig(VersionedEntity):
    """Model provider configurations."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    models: list[ModelEntry] = field(default_factory=list)
    # Default model ID for routing if no explicit selection.
    default_model_id: str = ""


# ---------------------------------------------------------------------------
# Routing Configuration (§12.2)
# ---------------------------------------------------------------------------

@dataclass
class RoutingRule:
    """Single routing rule."""

    # Rule ID (must be unique within the config).
    id: str
    # Task pattern (glob or regex).
    pattern: str
    # Target model ID to route to.
    model_id: str
    # Priority (higher = checked first; default 0).
    priority: int = 0


@dataclass
class RoutingConfig(VersionedEntity):
    """Routing rules for COMPASS."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    rules: list[RoutingRule] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MCP Configuration (§12.2 — Model Context Protocol servers)
# ---------------------------------------------------------------------------

@dataclass
class MCPServerEntry:
    """Single MCP server configuration."""

    id: str
    name: str
    # Command to launch the server (e.g., "npx", "-y", "@modelcontextprotocol/server-...").
    command: list[str] = field(default_factory=list)
    # Environment variables for the server process.
    env: dict[str, str] = field(default_factory=dict)
    # Timeout for server initialization (seconds).
    init_timeout_sec: int = 10
    # Trust level: "trusted", "sandboxed", "untrusted".
    trust_level: str = "sandboxed"


@dataclass
class MCPConfig(VersionedEntity):
    """MCP server configurations."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    servers: list[MCPServerEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Permissions Configuration (§12.2 — user/workspace policies)
# ---------------------------------------------------------------------------

@dataclass
class PermissionsConfig(VersionedEntity):
    """Permission policies."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    # Allow filesystem writes outside workspace.
    allow_external_writes: bool = False
    # Allow network access for tools.
    allow_network: bool = True
    # Allow execution of arbitrary shell commands.
    allow_shell_exec: bool = True
    # Require confirmation for destructive operations.
    confirm_destructive: bool = True


# ---------------------------------------------------------------------------
# Privacy Configuration (§12.2 — telemetry, logging, redaction)
# ---------------------------------------------------------------------------

@dataclass
class PrivacyConfig(VersionedEntity):
    """Privacy and telemetry settings.

    The transmission fields implement spec §4.5 / TB-9: context leaves the
    machine only when the privacy policy allows it, and never silently.
    Defaults are restrictive — external transmission is off until the user
    enables it and names the providers.
    """

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    # Enable telemetry collection.
    enable_telemetry: bool = False
    # Redact credentials in logs/diagnostics (non-overridable, system security).
    redact_credentials: bool = True
    # Log level: "debug", "info", "warning", "error".
    log_level: str = "info"
    # --- External transmission (TB-9) ---
    # Master switch for sending context to any external (cloud) provider.
    allow_external_transmission: bool = False
    # Hard local-only mode: no external provider may receive context at all.
    local_only: bool = False
    # Require an explicit user confirmation before each external transmission.
    require_confirmation: bool = True
    # Providers allowed to receive context (empty = none).
    allowed_providers: list[str] = field(default_factory=list)
    # Apply secret redaction to the payload before it leaves the machine.
    redact_before_transmission: bool = True


# ---------------------------------------------------------------------------
# Paths Configuration (§12.2 — workspace-specific overrides)
# ---------------------------------------------------------------------------

@dataclass
class PathsConfig(VersionedEntity):
    """Path overrides for workspace."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    # Workspace root override (relative or absolute).
    workspace_root: str = ""
    # Database path override (relative to SERAPHIM root).
    db_path: str = ""


# ---------------------------------------------------------------------------
# UI Configuration (§12.2 — Electron UI preferences)
# ---------------------------------------------------------------------------

@dataclass
class UIConfig(VersionedEntity):
    """UI preferences."""

    SCHEMA_VERSION = 1
    MIN_SUPPORTED_VERSION = 1

    schema_version: int = 1
    # Theme: "light", "dark", "auto".
    theme: str = "auto"
    # Font size (px).
    font_size: int = 14
    # Show line numbers in code blocks.
    show_line_numbers: bool = True
    # Window dimensions (width, height).
    window_width: int = 1200
    window_height: int = 800
