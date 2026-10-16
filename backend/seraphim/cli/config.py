"""Configuration validation CLI command."""

import sys
from pathlib import Path

import click

from seraphim.contracts.sanitization import sanitize_text
from seraphim.sanctum.validator import validate_config_files


@click.group(name="config")
def config_group():
    """Manage and validate SERAPHIM configuration."""


@config_group.command(name="validate")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="Root configuration directory (defaults to current working directory)",
)
def validate_command(config_dir: Path | None):
    """Validate SERAPHIM configuration files.

    Checks:
    - YAML syntax
    - Schema compliance
    - Unknown critical fields
    - Duplicate IDs
    - Protected field conflicts
    """
    if config_dir is None:
        config_dir = Path.cwd()

    result = validate_config_files(config_dir)

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
