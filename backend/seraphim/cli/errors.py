"""Shared CLI error presentation (S09).

Commands that can raise a structured ``SeraphimError`` use :func:`handle_errors`
so the user sees the stable error code and the safe message instead of a
traceback.  The error text is the sanitized ``safe_message``, so a secret can
never be printed here.

Scope note: every CLI command that can raise a ``SeraphimError`` is wrapped, so
no command surfaces a raw traceback (the S07/S08 identity and config commands
were wrapped as part of the C4 review follow-up, closing the S10 debt).
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
