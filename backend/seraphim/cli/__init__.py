"""CLI commands for SERAPHIM configuration management and diagnostics."""

from .config import config_group
from .doctor import doctor_command
from .logs import logs_group
from .status import status_command

__all__ = ["config_group", "doctor_command", "logs_group", "status_command"]
