# OBSERVATORY — events, logs, metrics.
#
# Public surface (S06 + S10):
#   EventBus / EventStore / Logger — structured events and redacted logging (S06)
#   run_doctor / build_status      — read-only diagnostics for CLI and GUI (S10)
#   read_log_tail                  — redacted log tailing (S10)

from seraphim.observatory.bus import EventBus
from seraphim.observatory.doctor import (
    CheckResult,
    DoctorReport,
    StatusReport,
    build_status,
    run_doctor,
)
from seraphim.observatory.logger import Logger
from seraphim.observatory.logs import LogTail, read_log_tail
from seraphim.observatory.store import EventStore

__all__ = [
    "CheckResult",
    "DoctorReport",
    "EventBus",
    "EventStore",
    "LogTail",
    "Logger",
    "StatusReport",
    "build_status",
    "read_log_tail",
    "run_doctor",
]
