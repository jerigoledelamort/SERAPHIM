"""Secret management and privacy inspection CLI commands (S09).

User-facing surface for the S09 guarantees:

- secrets live in platform secure storage and are only ever shown masked;
- a value is never passed on the command line (no shell history leak);
- the privacy summary is printed before any context would leave the machine;
- ``secrets audit`` scans the root for secret material in configs/logs/exports.

Commands never print a stored value: ``show`` prints a mask, ``list`` prints
reference names, and ``audit`` prints paths only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from seraphim.cli.errors import handle_errors
from seraphim.contracts.errors import SeraphimError
from seraphim.sanctum.export import build_safe_export, find_secret_material
from seraphim.sanctum.loader import load_config
from seraphim.sanctum.privacy import (
    DATA_CATEGORIES,
    PrivacyPolicy,
    TransmissionRequest,
    evaluate_transmission,
    render_summary,
)
from seraphim.sanctum.secrets import (
    SecretStore,
    create_secret_store,
    validate_secret_ref,
)


@click.group(name="secrets")
def secrets_group():
    """Manage provider secrets (platform secure storage; never plaintext)."""


def _resolve_root(config_dir: Path | None) -> Path:
    return config_dir if config_dir is not None else Path.cwd()


def _store(config_dir: Path | None) -> SecretStore:
    return create_secret_store(_resolve_root(config_dir))


def _read_value(value_stdin: bool, from_env: str | None, prompt: str) -> str:
    """Read a secret value without exposing it on the command line.

    Priority: ``--from-env VAR`` → ``--stdin`` → hidden interactive prompt.
    A ``--value`` option is deliberately not offered: command-line arguments are
    visible in process listings and shell history.
    """
    if from_env:
        import os

        value = os.environ.get(from_env)
        if not value:
            raise click.ClickException(f"Environment variable {from_env} is not set.")
        return value
    if value_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
        if not value:
            raise click.ClickException("No value received on stdin.")
        return value
    value = click.prompt(prompt, hide_input=True, confirmation_prompt=True)
    return value


def _value_options(func):
    func = click.option(
        "--from-env",
        "from_env",
        default=None,
        metavar="VAR",
        help="Read the value from an environment variable.",
    )(func)
    func = click.option(
        "--stdin",
        "value_stdin",
        is_flag=True,
        default=False,
        help="Read the value from stdin (for scripts).",
    )(func)
    func = click.option(
        "--config-dir",
        type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
        help="SERAPHIM root directory (defaults to current working directory)",
    )(func)
    return func


@secrets_group.command(name="set")
@click.argument("ref")
@_value_options
@handle_errors
def set_command(ref: str, value_stdin: bool, from_env: str | None, config_dir: Path | None):
    """Store a secret under REF (creates or overwrites)."""
    validate_secret_ref(ref)
    value = _read_value(value_stdin, from_env, f"Secret value for {ref}")
    store = _store(config_dir)
    store.set(ref, value)
    click.secho(f"Stored secret '{ref}' in {store.info.backend} store.", fg="green")
    click.echo(f"  location: {store.info.location}")


@secrets_group.command(name="list")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@handle_errors
def list_command(config_dir: Path | None):
    """List stored secret references (names only, never values)."""
    store = _store(config_dir)
    click.secho(f"Secret store: {store.info.backend}", bold=True)
    click.echo(f"  location: {store.info.location}")
    click.echo(f"  encrypted at rest: {store.info.encrypted_at_rest}")
    refs = store.list_refs()
    click.echo(f"  references: {len(refs)}")
    for ref in refs:
        click.echo(f"    - {ref}")


@secrets_group.command(name="show")
@click.argument("ref")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@handle_errors
def show_command(ref: str, config_dir: Path | None):
    """Show a masked view of a stored secret (never the value)."""
    validate_secret_ref(ref)
    store = _store(config_dir)
    click.echo(f"{ref}: {store.masked(ref)}")


@secrets_group.command(name="rotate")
@click.argument("ref")
@_value_options
@handle_errors
def rotate_command(ref: str, value_stdin: bool, from_env: str | None, config_dir: Path | None):
    """Replace the value of an existing secret REF."""
    validate_secret_ref(ref)
    value = _read_value(value_stdin, from_env, f"New value for {ref}")
    store = _store(config_dir)
    store.rotate(ref, value)
    click.secho(f"Rotated secret '{ref}'.", fg="green")


@secrets_group.command(name="delete")
@click.argument("ref")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@handle_errors
def delete_command(ref: str, yes: bool, config_dir: Path | None):
    """Delete a stored secret REF."""
    validate_secret_ref(ref)
    store = _store(config_dir)
    if not store.has(ref):
        raise click.ClickException(f"No secret is stored under reference '{ref}'.")
    if not yes:
        click.confirm(f"Delete secret '{ref}'? This cannot be undone.", abort=True)
    removed = store.delete(ref)
    if removed:
        click.secho(f"Deleted secret '{ref}'.", fg="green")
    else:
        raise click.ClickException(f"No secret is stored under reference '{ref}'.")


@secrets_group.command(name="audit")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable output.")
@handle_errors
def audit_command(config_dir: Path | None, as_json: bool):
    """Scan the root for secret material in configs, logs and exports.

    Checks the secret-free export payload and every text file under the root for
    known secret values and secret-like patterns. Reports file paths only.
    """
    root = _resolve_root(config_dir)
    store = _store(config_dir)
    known = []
    for ref in store.list_refs():
        try:
            known.append(store.get(ref))
        except SeraphimError:
            # An unreadable secret is reported, not fatal: the audit continues.
            known.append(None)

    findings: list[str] = []

    try:
        payload = build_safe_export(root, secret_store=store)
        for path in find_secret_material(payload, known_secrets=[v for v in known if v]):
            findings.append(f"export{path[1:]}")
    except SeraphimError as exc:
        findings.append(f"export: {exc.code}")

    findings.extend(_scan_files(root, [v for v in known if v]))

    if as_json:
        click.echo(json.dumps({"findings": findings, "checked_refs": len(store.list_refs())}))
    else:
        if findings:
            click.secho(f"Secret material detected in {len(findings)} location(s):", fg="red")
            for finding in findings:
                click.echo(f"  - {finding}")
        else:
            click.secho("No secret material found in configs, logs or exports.", fg="green")
    sys.exit(1 if findings else 0)


_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
_TEXT_SUFFIXES = {".yaml", ".yml", ".json", ".md", ".txt", ".log", ".ini", ".toml", ".env", ""}


def _scan_files(root: Path, known: list[str]) -> list[str]:
    """Return relative paths of files containing secret material."""
    from seraphim.contracts.sanitization import sanitize_text

    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if (known and any(value in text for value in known)) or sanitize_text(text) != text:
            findings.append(path.relative_to(root).as_posix())
    return findings


@click.group(name="privacy")
def privacy_group():
    """Inspect what would be sent to an external provider."""


@privacy_group.command(name="summary")
@click.option("--provider", required=True, help="Provider that would receive the context.")
@click.option("--model", default="", help="Model name (optional).")
@click.option(
    "--categories",
    default="",
    help=f"Comma-separated local data categories. Known: {', '.join(sorted(DATA_CATEGORIES))}.",
)
@click.option("--purpose", default="chat", help="Why the context is being sent.")
@click.option("--local", "is_local", is_flag=True, default=False, help="Provider runs locally.")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable output.")
@handle_errors
def summary_command(
    provider: str,
    model: str,
    categories: str,
    purpose: str,
    is_local: bool,
    config_dir: Path | None,
    as_json: bool,
):
    """Show the privacy summary and decision for a provider request."""
    root = _resolve_root(config_dir)
    config = load_config(root)
    policy = PrivacyPolicy.from_config(config.privacy)

    parsed = tuple(c.strip() for c in categories.split(",") if c.strip())
    request = TransmissionRequest(
        provider=provider,
        categories=parsed,
        model=model,
        purpose=purpose,
        external=not is_local,
    )
    decision = evaluate_transmission(policy, request)

    if as_json:
        click.echo(json.dumps(decision.to_dict(), ensure_ascii=False))
    else:
        click.echo(render_summary(decision.summary))
        click.echo()
        click.secho(
            f"Decision: {'ALLOWED' if decision.allowed else 'DENIED'} ({decision.reason})",
            fg="green" if decision.allowed else "red",
            bold=True,
        )
        click.echo(f"  {decision.detail}")
        if decision.allowed and decision.requires_confirmation:
            click.echo("  Confirmation: the user must confirm before this transfer.")

    sys.exit(0 if decision.allowed else 1)
