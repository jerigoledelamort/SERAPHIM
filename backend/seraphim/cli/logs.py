"""Log tailing CLI command (S10).

Reads the tail of a log file under ``<root>/logs``.  Uses the same service API
(`read_log_tail`) that the GUI will call.

Exit codes:
    0 — success (log file read and displayed).
    1 — error (file not found, negative line count, etc.).
    2 — usage error (bad arguments; automatic from Click).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from seraphim.cli.errors import handle_errors
from seraphim.observatory.logs import read_log_tail

COMPONENT = "cli.logs"


@click.group(name="logs")
def logs_group():
    """Inspect SERAPHIM log files."""


@logs_group.command(name="tail")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
@click.option(
    "--lines", "-n",
    type=int,
    default=50,
    help="Number of trailing lines to show (default: 50).",
)
@click.option(
    "--file", "-f",
    "name",
    default=None,
    help="Log file name (relative path or basename). Defaults to most recent.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable JSON output.")
@handle_errors
def tail_command(config_dir: Path | None, lines: int, name: str | None, as_json: bool):
    """Show the tail of a SERAPHIM log file.

    Reads the last *lines* from the most recently modified log file under
    ``<root>/logs`` (or a specific file with ``--file``).  All lines are
    sanitized so that no secret material is leaked.
    """
    if lines < 0:
        click.secho("error [VALIDATION_FAILED]: --lines must be zero or greater.", fg="red", err=True)
        raise SystemExit(1)

    root = config_dir if config_dir is not None else Path.cwd()

    try:
        tail = read_log_tail(root, lines=lines, name=name)
    except Exception as exc:
        # SeraphimError is caught by handle_errors; this catches others.
        click.secho(f"error [LOG_READ_ERROR]: {exc}", fg="red", err=True)
        raise SystemExit(1) from None

    if as_json:
        click.echo(json.dumps(tail.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0)

    if not tail.selected:
        click.secho("No log files found under logs/.", fg="yellow")
        if tail.files:
            click.echo(f"  Available files: {', '.join(tail.files)}")
        sys.exit(0)

    click.secho(f"logs/{tail.selected} ({len(tail.lines)} lines, truncated={tail.truncated})", bold=True)
    click.echo()

    for line in tail.lines:
        click.echo(line)

    if tail.truncated:
        click.echo()
        click.secho("  ... (file truncated; use more --lines to read earlier entries)", fg="yellow")

    sys.exit(0)
