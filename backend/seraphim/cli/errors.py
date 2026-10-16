"""Shared CLI error presentation (S09).

Commands that can raise a structured ``SeraphimError`` use :func:`handle_errors`
so the user sees the stable error code and the safe message instead of a
traceback.  The error text is the sanitized ``safe_message``, so a secret can
never be printed here.

Scope note: only the S09 commands are wrapped for now; the S07/S08 commands
still let errors propagate.  A uniform CLI error surface belongs to S10
(CLI foundation and doctor).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import click

from seraphim.contracts.errors import SeraphimError

F = TypeVar("F", bound=Callable[..., Any])


def handle_errors(func: F) -> F:
    """Present ``SeraphimError`` as a structured CLI message and exit non-zero."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except SeraphimError as exc:
            click.secho(f"error [{exc.code}]: {exc.safe_message}", fg="red", err=True)
            raise SystemExit(1) from exc

    return wrapper  # type: ignore[return-value]
