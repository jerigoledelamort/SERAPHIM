"""Configuration validation, display and export/import CLI commands (S07 + S10 + S11)."""

import json
import sys
from pathlib import Path

import click

from seraphim.cli.errors import handle_errors
from seraphim.contracts.sanitization import sanitize_dict, sanitize_text
from seraphim.sanctum.export_import import (
    export_to_archive,
    import_from_archive,
)
from seraphim.sanctum.loader import load_config
from seraphim.sanctum.validator import validate_config_files

COMPONENT = "cli.config"


def _resolve_root(config_dir: Path | None) -> Path:
    return config_dir if config_dir is not None else Path.cwd()


@click.group(name="config")
def config_group():
    """Manage and validate SERAPHIM configuration."""


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@config_group.command(name="show")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def show_command(config_dir: Path | None, as_json: bool):
    """Display the resolved SERAPHIM configuration (without secrets).

    Loads all configuration domains with 5-level priority merging and prints
    a summary.  Sensitive values are never included: the config holds only
    ``secret_ref`` references, and every field is sanitized before output.
    """
    root = _resolve_root(config_dir)
    config = load_config(root)

    if as_json:
        # Serialize each domain to its dataclass dict (sanitized).
        data = {
            domain: sanitize_dict(getattr(config, domain).to_dict())
            for domain in (
                "runtime", "providers", "routing", "mcp",
                "permissions", "privacy", "paths", "ui",
            )
        }
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(0)

    click.secho("Resolved configuration", bold=True)
    click.echo(f"  Root: {root}")
    click.echo()
    for line in _config_summary_lines(config):
        click.echo(line)
    sys.exit(0)


def _config_summary_lines(config) -> list[str]:
    """Build human-readable per-domain summary lines (no secrets)."""
    rt, pr, ro, mcp = config.runtime, config.providers, config.routing, config.mcp
    perm, priv, paths, ui = config.permissions, config.privacy, config.paths, config.ui

    return [
        f"  runtime: task_timeout_sec={rt.task_timeout_sec}, "
        f"max_parallel_tools={rt.max_parallel_tools}, enable_anti_loop={rt.enable_anti_loop}",
        f"  providers: {len(pr.models)} model(s), default_model_id={pr.default_model_id!r}",
        f"  routing: {len(ro.rules)} rule(s)",
        f"  mcp: {len(mcp.servers)} server(s)",
        f"  permissions: allow_external_writes={perm.allow_external_writes}, "
        f"allow_network={perm.allow_network}, confirm_destructive={perm.confirm_destructive}",
        f"  privacy: redact_credentials={priv.redact_credentials}, "
        f"allow_external_transmission={priv.allow_external_transmission}, "
        f"local_only={priv.local_only}",
        f"  paths: db_path={paths.db_path!r} (empty = default)",
        f"  ui: theme={ui.theme!r}, font_size={ui.font_size}",
    ]


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@config_group.command(name="validate")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Root configuration directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def validate_command(config_dir: Path | None, as_json: bool):
    """Validate SERAPHIM configuration files.

    Checks:
    - YAML syntax
    - Schema compliance
    - Unknown critical fields
    - Duplicate IDs
    - Protected field conflicts
    """
    root = _resolve_root(config_dir)

    result = validate_config_files(root)

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0 if result.valid else 1)

    if result.valid:
        click.secho("Configuration validation passed", fg="green")
        sys.exit(0)
    else:
        click.secho("Configuration validation failed", fg="red")
        click.echo()

        for issue in result.issues:
            # Issue severity (error/warning)
            severity_color = "red" if issue.severity == "error" else "yellow"
            click.secho(f"[{issue.severity.upper()}]", fg=severity_color, bold=True)

            # Message (sanitized: a validation message can quote a config value)
            click.echo(f"  {sanitize_text(issue.message)}")

            # File location and key if available
            if issue.file:
                location = issue.file
                if issue.key:
                    location += f" (key: {issue.key})"
                click.echo(f"  File: {location}")

            # Fix instruction
            if issue.fix:
                click.secho(f"  Fix: {issue.fix}", fg="cyan")

            click.echo()

        sys.exit(1)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@config_group.command(name="export")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option(
    "--out",
    "output_path",
    type=click.Path(writable=True, path_type=Path, allow_dash=True),
    default=None,
    help="Destination zip path (default: <root>/data/backups/seraphim-export-<ts>.zip)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def export_command(config_dir: Path | None, output_path: Path | None, as_json: bool):
    """Export SERAPHIM configuration, identity, locale, theme and skills.

    Secrets are **never** included — only references (``secret_ref``) and
    metadata about the secret store.
    """
    root = _resolve_root(config_dir)

    try:
        manifest = export_to_archive(root, output_path=output_path)
    except Exception as exc:
        click.secho(f"Export failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    if as_json:
        click.echo(json.dumps(manifest, indent=2, ensure_ascii=False))
        sys.exit(0)

    click.secho("SERAPHIM configuration export", bold=True, fg="green")
    click.echo(f"  Root: {root}")
    click.echo(f"  Domains: {', '.join(manifest['domains'])}")
    click.echo(f"  Files: {manifest['file_count']}")
    click.echo(f"  Format version: {manifest['export_format_version']}")
    click.echo(f"  Created: {manifest['created_at']}")
    click.echo()
    click.echo("  Excluded:")
    for key, desc in manifest["excluded"].items():
        click.echo(f"    - {key}: {desc}")
    sys.exit(0)


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@config_group.command(name="import")
@click.argument("archive_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Target SERAPHIM root directory (defaults to current working directory).",
)
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply the import (default: dry-run — show diff only).",
)
@click.option(
    "--current-root",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Current root to back up before applying (defaults to --config-dir).",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def import_command(
    archive_path: Path,
    config_dir: Path | None,
    apply: bool,
    current_root: Path | None,
    as_json: bool,
):
    """Import SERAPHIM configuration from an export archive.

    By default performs a **dry-run**: shows what would change without writing
    anything.  Use ``--apply`` to perform the actual import.

    The import process:
      1. Validates the archive manifest and format version.
      2. Guards against path-traversal (rejects entries outside the root).
      3. Shows a diff of what would change (or applies atomically with
         ``--apply``).
      4. Creates a backup of the current config before writing.
      5. On partial failure, automatically rolls back from the backup.

    Secrets are never included in the archive — only ``secret_ref`` references
    and backend metadata.
    """
    target = config_dir if config_dir is not None else Path.cwd()
    current = current_root if current_root is not None else target

    try:
        result = import_from_archive(
            archive_path, target,
            dry_run=not apply,
            current_root=current,
        )
    except Exception as exc:
        click.secho(f"Import failed: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    if as_json:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    click.secho("SERAPHIM configuration import", bold=True, fg="magenta")
    click.echo(f"  Archive: {archive_path}")
    click.echo(f"  Target: {target}")
    click.echo(f"  Mode: {'dry-run' if result['dry_run'] else 'apply'}")
    click.echo()

    manifest = result.get("manifest", {})
    click.echo("  Manifest:")
    click.echo(f"    Format version: {manifest.get('export_format_version', '?')}")
    click.echo(f"    SERAPHIM version: {manifest.get('seraphim_version', '?')}")
    click.echo(f"    Created: {manifest.get('created_at', '?')}")
    click.echo()

    diff = result.get("diff", {})
    if diff.get("added"):
        click.secho(f"  Files to add ({len(diff['added'])}):", bold=True)
        for f in diff["added"]:
            click.echo(f"    + {f}")
    if diff.get("modified"):
        click.secho(f"  Files to modify ({len(diff['modified'])}):", bold=True)
        for f in diff["modified"]:
            click.echo(f"    ~ {f}")
    if diff.get("removed"):
        click.secho(f"  Files to remove ({len(diff['removed'])}):", bold=True)
        for f in diff["removed"]:
            click.echo(f"    - {f}")
    if diff.get("unchanged"):
        click.echo(f"  Unchanged: {len(diff['unchanged'])}")

    if not result["dry_run"]:
        backup = result.get("backup_path", "N/A")
        click.echo()
        click.secho(f"  Backup created: {backup}", fg="green")
        click.secho("  Import applied successfully.", fg="green")
    else:
        click.echo()
        click.secho("  (Dry-run — use --apply to import.)", fg="yellow")

    sys.exit(0)
