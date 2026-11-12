# WINGS process runner (S22): runs one executable with an argv list (never a shell string),
# a sandbox cwd, an allowlisted environment, a timeout, bounded and redacted output, and
# cancellation. The whole process tree is killed through a Windows Job Object or a POSIX
# process group. Callers reach this only through a WINGS tool, after AEGIS has decided.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import sanitize_text
from seraphim.wings.fs_paths import FsRoot

COMPONENT = "wings.process"

MAX_OUTPUT_BYTES = 65_536
MAX_TIMEOUT_SECONDS = 120
MAX_ARGS = 64
MAX_ARG_CHARS = 1_024
_POLL_SECONDS = 0.05
_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT", "LANG", "LC_ALL")
_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool
    cancelled: bool
    duration_ms: int


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def _error(code: str, message: str) -> SeraphimError:
    return SeraphimError(code=code, component=COMPONENT, safe_message=message)


def _validate_argv(argv: Sequence[str]) -> list[str]:
    if not argv or not all(isinstance(a, str) for a in argv):
        raise _error(ErrorCode.VALIDATION_FAILED, "argv must be a non-empty list of strings.")
    if len(argv) > MAX_ARGS or any(len(a) > MAX_ARG_CHARS or "\x00" in a for a in argv):
        raise _error(ErrorCode.VALIDATION_FAILED, "argv exceeds the argument limits.")
    return list(argv)


def resolve_executable(name: str, env: Mapping[str, str], allowed: Collection[str]) -> str:
    if not name or any(sep in name for sep in ("/", "\\")) or ":" in name:
        raise _error(ErrorCode.VALIDATION_FAILED, "Executable must be a bare name from the allowlist.")
    if name not in allowed:
        raise _error(ErrorCode.VALIDATION_FAILED, "Executable is not in the allowlist.")
    found = shutil.which(name, path=env.get("PATH", ""))
    if found is None:
        raise _error(ErrorCode.TOOL_NOT_FOUND, "Executable is not available.")
    return found


def build_env(source: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {key: source[key] for key in _ENV_ALLOWLIST if key in source}
    for key, value in (extra or {}).items():
        if not key.isidentifier() or "\x00" in value:
            raise _error(ErrorCode.VALIDATION_FAILED, "Environment variable name or value is invalid.")
        env[key] = value
    return env


def redact_output(text: str) -> str:
    return sanitize_text(text).replace("\r", "")


class _Bounded:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: list[bytes] = []
        self._size = 0
        self.truncated = False
        self._lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self._lock:
            room = self._limit - self._size
            if room <= 0:
                self.truncated = self.truncated or bool(data)
                return
            if len(data) > room:
                data = data[:room]
                self.truncated = True
            self._chunks.append(data)
            self._size += len(data)

    def text(self) -> str:
        with self._lock:
            return redact_output(b"".join(self._chunks).decode("utf-8", errors="replace"))


def _pump(stream: object, sink: _Bounded) -> threading.Thread:
    def run() -> None:
        assert hasattr(stream, "read")
        while True:
            chunk = stream.read(4096)  # type: ignore[attr-defined]
            if not chunk:
                break
            sink.feed(chunk)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class _JobObject:
    """Windows Job Object with KILL_ON_JOB_CLOSE: closing the handle kills every process in it."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateJobObjectW.restype = wintypes.HANDLE
        self._k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self._k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        self._k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = self._k32.CreateJobObjectW(None, None)
        if not handle:
            raise _error(ErrorCode.INTERNAL_ERROR, "Could not create a process job.")
        self._handle = handle
        self._ctypes = ctypes

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _ExtLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _ExtLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            self._k32.CloseHandle(handle)
            raise _error(ErrorCode.INTERNAL_ERROR, "Could not configure the process job.")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not self._k32.AssignProcessToJobObject(self._handle, int(process._handle)):  # type: ignore[attr-defined]
            raise _error(ErrorCode.INTERNAL_ERROR, "Could not place the process into its job.")

    def terminate(self) -> None:
        self._k32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        self._k32.CloseHandle(self._handle)


def _kill_tree(process: subprocess.Popen[bytes], job: _JobObject | None) -> None:
    if job is not None:
        job.terminate()
    elif process.poll() is None:
        try:
            os.killpg(process.pid, 9)
        except (ProcessLookupError, PermissionError):
            process.kill()


def run_process(
    argv: Sequence[str],
    *,
    cwd: FsRoot,
    allowed: Collection[str],
    env_source: Mapping[str, str] | None = None,
    timeout_seconds: int = 30,
    cancel: CancelToken | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ProcessResult:
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
        raise _error(ErrorCode.VALIDATION_FAILED, "timeout must be an integer number of seconds.")
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise _error(ErrorCode.VALIDATION_FAILED, f"timeout must be 1..{MAX_TIMEOUT_SECONDS} seconds.")
    args = _validate_argv(argv)
    env = build_env(os.environ if env_source is None else env_source)
    executable = resolve_executable(args[0], env, allowed)
    args[0] = executable
    workdir = str(cwd.path)

    flags: dict[str, object] = {}
    if _WINDOWS:
        flags["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        flags["start_new_session"] = True

    started = clock()
    try:
        process = subprocess.Popen(
            args,
            cwd=workdir,
            env=env,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **flags,  # type: ignore[arg-type]
        )
    except OSError:
        raise _error(ErrorCode.INTERNAL_ERROR, "Process could not be started.") from None

    job: _JobObject | None = None
    if _WINDOWS:
        try:
            job = _JobObject()
            job.assign(process)
        except SeraphimError:
            _kill_tree(process, None)
            process.wait()
            if job is not None:
                job.close()
            raise

    out, err = _Bounded(MAX_OUTPUT_BYTES), _Bounded(MAX_OUTPUT_BYTES)
    readers = [_pump(process.stdout, out), _pump(process.stderr, err)]
    timed_out = False
    cancelled = False
    try:
        while process.poll() is None:
            if cancel is not None and cancel.cancelled:
                cancelled = True
                break
            if clock() - started >= timeout_seconds:
                timed_out = True
                break
            time.sleep(_POLL_SECONDS)
        if cancelled or timed_out:
            _kill_tree(process, job)
        process.wait()
        for reader in readers:
            reader.join(timeout=2)
    finally:
        if process.poll() is None:
            _kill_tree(process, job)
            process.wait()
        if job is not None:
            job.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    code = process.returncode
    return ProcessResult(
        exit_code=None if (timed_out or cancelled) else code,
        stdout=out.text(),
        stderr=err.text(),
        stdout_truncated=out.truncated,
        stderr_truncated=err.truncated,
        timed_out=timed_out,
        cancelled=cancelled,
        duration_ms=max(0, int((clock() - started) * 1000)),
    )
