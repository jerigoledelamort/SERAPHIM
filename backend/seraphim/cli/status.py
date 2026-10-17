"""System status CLI command (S10).

Provides a compact, read-only snapshot of the SERAPHIM system for scripts and
CI pipelines.  Uses the same service API (`build_status`) that the GUI will
call.

Exit codes:
    0 — healthy (no errors; warnings are non-blocking).
    1 — one or more checks reported an error.
    2 — usage error (bad arguments; automatic from Click).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from seraphim.cli.errors import handle_errors
from seraphim.observatory.doctor import build_status

COMPONENT = "cli.status"


@click.command(name="status")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def status_command(config_dir: Path | None, as_json: bool):
    """Show a compact, read-only system snapshot.

    Displays runtime info, configuration validity, database state, secret
    storage backend, identity settings, and diagnostic checks.

    This command is read-only: it never creates files or changes any state.
    """
    root = config_dir if config_dir is not None else Path.cwd()

    status = build_status(root)

    if as_json:
        click.echo(json.dumps(status.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0 if status.healthy else 1)

    # ── Human-readable output ──────────────────────────────────────────

    click.secho("SERAPHIM Status", bold=True, fg="magenta")
    click.echo(f"  Root: {status.root}")
    click.echo()

    # Runtime
    rt = status.runtime
    click.echo(f"  Python: {rt.get('python', '?')}")
    click.echo(f"  Platform: {rt.get('platform', '?')}")
    click.echo()

    # Config
    cfg = status.config
    click.echo(f"  Configuration: valid={cfg['valid']} ({cfg['issues']} issue(s))")

    # Database
    db = status.database
    if db.get("exists"):
        if db.get("initialized"):
            db_color = "green"
            db_status = f"v{db['current_version']} (up to date)"
        else:
            db_color = "red"
            db_status = "exists but uninitialized"
    else:
        db_color = "yellow"
        db_status = "not initialized (no file)"
    click.echo(f"  Database: {click.style(db_status, fg=db_color)}")

    # Secrets
    sec = status.secrets
    if sec.get("available"):
        sec_color = "green"
        sec_status = f"{sec.get('backend', '?')} ({sec.get('references', 0)} reference(s))"
    else:
        sec_color = "yellow"
        sec_status = f"unavailable ({sec.get('error_code', '?')})"
    click.echo(f"  Secrets: {click.style(sec_status, fg=sec_color)}")

    # Identity
    ident = status.identity
    if ident.get("valid"):
        ident_color = "green"
        ident_status = (
            f"ui={ident.get('ui_language', '?')}, "
            f"response={ident.get('response_language', '?')}"
        )
    else:
        ident_color = "red"
        ident_status = f"invalid ({ident.get('error_code', '?')})"
    click.echo(f"  Identity: {click.style(ident_status, fg=ident_color)}")

    click.echo()

    if status.healthy:
        click.secho("Overall: HEALTHY", fg="green", bold=True)
    else:
        click.secho("Overall: ERRORS DETECTED", fg="red", bold=True)

    sys.exit(0 if status.healthy else 1)
