"""Diagnostic check CLI command (S10).

Runs read-only checks against the SERAPHIM root and reports issues in a format
understandable without reading the source code.  Uses the same service API
(`run_doctor`) that the GUI will call, so no business logic is duplicated.

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
from seraphim.observatory.doctor import run_doctor

COMPONENT = "cli.doctor"


@click.command(name="doctor")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def doctor_command(config_dir: Path | None, as_json: bool):
    """Run diagnostic checks on the SERAPHIM root.

    Verifies: root directory, standard layout, filesystem permissions,
    configuration validity, database and migrations, secret storage backend,
    identity settings, runtime prerequisites, and local API availability.

    This command is read-only: it never creates files, applies migrations,
    or changes any configuration.
    """
    root = config_dir if config_dir is not None else Path.cwd()

    report = run_doctor(root)

    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0 if report.healthy else 1)

    # ── Human-readable output ──────────────────────────────────────────

    click.secho("SERAPHIM Doctor", bold=True, fg="magenta")
    click.echo(f"  Root: {report.root}")
    click.echo()

    for check in report.checks:
        if check.severity == "ok":
            icon = click.style("[PASS]", fg="green")
        elif check.severity == "warning":
            icon = click.style("[WARN]", fg="yellow")
        else:
            icon = click.style("[FAIL]", fg="red")

        click.echo(f"  {icon} {check.title}")
        if check.summary:
            click.echo(f"         {check.summary}")
        if check.remediation:
            click.echo(f"         Fix: {check.remediation}")
        click.echo()

    # Summary
    click.echo("-" * 40)
    if report.healthy:
        click.secho("Overall status: HEALTHY", fg="green", bold=True)
        if report.warnings:
            click.echo(f"  Warnings: {len(report.warnings)} (non-blocking)")
            for w in report.warnings:
                click.echo(f"    - {w.title}: {w.summary}")
    else:
        click.secho("Overall status: ERRORS DETECTED", fg="red", bold=True)
        click.echo(f"  Errors: {len(report.errors)}")
        for e in report.errors:
            click.echo(f"    - {e.title}: {e.summary}")
            if e.remediation:
                click.echo(f"      Fix: {e.remediation}")

    sys.exit(1 if not report.healthy else 0)
