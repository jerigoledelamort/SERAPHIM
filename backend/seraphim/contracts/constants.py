# SERAPHIM contracts — shared constants (S04).
# Error codes, ID prefixes, and enums used across all subsystems.

from __future__ import annotations

# ---------------------------------------------------------------------------
# ID prefixes (CONTRACTS.md §9, spec §4.1, §14.1)
# ---------------------------------------------------------------------------

ID_PREFIXES: frozenset[str] = frozenset(
    {
        "task",
        "step",
        "call",
        "event",
        "session",
        "artifact",
        "project",
        "skill",
        "integration",
        "provider",
        "model",
        "checkpoint",
        "memory",
        "doc",
        "file",
        "symbol",
        "policy",
        "approval",
        "eval",
        "run",
        "result",
        "correlation",
        "migration",
        "component",
    }
)

# ---------------------------------------------------------------------------
# Severity levels (spec §4.16)
# ---------------------------------------------------------------------------

SEVERITY_LEVELS: tuple[str, ...] = ("INFO", "WARN", "ERROR", "CRITICAL")

# ---------------------------------------------------------------------------
# Risk levels (spec §4.8, §7.4)
# ---------------------------------------------------------------------------

RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")

# ---------------------------------------------------------------------------
# Side effect categories (spec §4.8, §7.4)
# ---------------------------------------------------------------------------

SIDE_EFFECTS: tuple[str, ...] = ("none", "read", "write", "external", "destructive")

# ---------------------------------------------------------------------------
# Task states (spec §4.1)
# ---------------------------------------------------------------------------

TASK_STATES: tuple[str, ...] = (
    "DRAFT",
    "READY",
    "RUNNING",
    "VERIFYING",
    "SUCCEEDED",
    "NEEDS_APPROVAL",
    "RETRYING",
    "PAUSED",
    "CANCELLED",
    "BLOCKED",
    "FAILED",
)

# ---------------------------------------------------------------------------
# Step states (spec §4.1)
# ---------------------------------------------------------------------------

STEP_STATES: tuple[str, ...] = (
    "PENDING",
    "READY",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
    "CANCELLED",
)

# ---------------------------------------------------------------------------
# Policy decisions (spec §4.3)
# ---------------------------------------------------------------------------

POLICY_DECISIONS: tuple[str, ...] = ("ALLOW", "DENY", "ASK_USER", "ALLOW_WITH_LIMITS")

# ---------------------------------------------------------------------------
# PULSE statuses (spec §4.17)
# ---------------------------------------------------------------------------

PULSE_STATUSES: tuple[str, ...] = (
    "ONLINE",
    "DEGRADED",
    "OFFLINE",
    "STARTING",
    "STOPPING",
    "UNKNOWN",
)
