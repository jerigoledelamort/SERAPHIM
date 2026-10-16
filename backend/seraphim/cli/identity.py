"""Identity inspection CLI commands (S08).

Minimal inspection surface for the acceptance criterion "active instructions
can be inspected without revealing secrets". Uses the same SANCTUM loader and
prompt composer as the runtime; it never prints raw secrets (preview redacts).
"""

from __future__ import annotations

from pathlib import Path

import click

from seraphim.sanctum.identity import load_identity
from seraphim.sanctum.prompt_composer import PromptComposer


@click.group(name="identity")
def identity_group():
    """Inspect SERAPHIM identity and the composed instruction prompt."""


def _resolve_root(config_dir: Path | None) -> Path:
    return config_dir if config_dir is not None else Path.cwd()


@identity_group.command(name="show")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
def show_command(config_dir: Path | None):
    """Show profile settings and the active instruction layers (no secrets)."""
    identity = load_identity(_resolve_root(config_dir))
    profile = identity.profile

    click.secho("Profile", bold=True)
    click.echo(f"  display_name: {profile.display_name}")
    click.echo(f"  ui_language: {profile.ui_language}")
    click.echo(f"  response_language: {profile.response_language}")
    click.echo(f"  default_task_mode: {profile.default_task_mode}")
    click.echo(f"  timezone: {profile.timezone}")
    click.echo()

    composition = PromptComposer(identity).compose()
    click.secho("Active layers (composition order)", bold=True)
    for entry in composition.inspect():
        flags = []
        if entry["truncated"]:
            flags.append("truncated")
        if entry["dropped"]:
            flags.append("dropped")
        flag_text = f" [{', '.join(flags)}]" if flags else ""
        click.echo(
            f"  [{entry['order']}] {entry['layer_id']:<20} "
            f"trust={entry['trust']:<8} source={entry['source']}{flag_text}"
        )


@identity_group.command(name="prompt-preview")
@click.option(
    "--config-dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    help="SERAPHIM root directory (defaults to current working directory)",
)
def prompt_preview_command(config_dir: Path | None):
    """Render the composed instruction prompt (secret-like values redacted)."""
    identity = load_identity(_resolve_root(config_dir))
    composition = PromptComposer(identity).compose()
    click.echo(composition.preview())
