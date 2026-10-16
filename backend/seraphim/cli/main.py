"""SERAPHIM CLI entry point."""

import click

from seraphim.cli.config import config_group
from seraphim.cli.identity import identity_group
from seraphim.cli.secrets import privacy_group, secrets_group


@click.group()
@click.version_option(version="0.1.0", prog_name="seraphim")
def cli():
    """SERAPHIM agent runtime — configuration and diagnostics."""


cli.add_command(config_group)
cli.add_command(identity_group)
cli.add_command(secrets_group)
cli.add_command(privacy_group)


if __name__ == "__main__":
    cli()
