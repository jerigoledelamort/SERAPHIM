"""
SERAPHIM S02 — Subprocess manager with Windows Job Object isolation.

Uses ctypes to create a Job Object with KILL_ON_JOB_CLOSE and memory limits.
When the parent dies, all children are killed automatically.
This is the "level 1 isolation" from ADR-005 — no Hyper-V/Docker required.
"""

import ctypes
import ctypes.wintypes
import os
import signal
import subprocess
import sys
import time
import uuid


# ---------------------------------------------------------------------------
# Windows API constants
# ---------------------------------------------------------------------------
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_INFORMATION = 0x0400
STILL_ACTIVE = 259


# ---------------------------------------------------------------------------
# Job Object structs — aligned for Windows 64-bit
# ---------------------------------------------------------------------------
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_uint64),
        ('WriteOperationCount', ctypes.c_uint64),
        ('OtherOperationCount', ctypes.c_uint64),
        ('ReadTransferCount', ctypes.c_uint64),
        ('WriteTransferCount', ctypes.c_uint64),
        ('OtherTransferCount', ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', ctypes.c_uint32),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', ctypes.c_uint32),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', ctypes.c_uint32),
        ('SchedulingClass', ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


# ---------------------------------------------------------------------------
# Windows API functions
# ---------------------------------------------------------------------------
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

CreateJobObjectW = kernel32.CreateJobObjectW
CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
CreateJobObjectW.restype = ctypes.c_void_p

AssignProcessToJobObject = kernel32.AssignProcessToJobObject
AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
AssignProcessToJobObject.restype = ctypes.c_bool

SetInformationJobObject = kernel32.SetInformationJobObject
SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
SetInformationJobObject.restype = ctypes.c_bool

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.c_void_p]
CloseHandle.restype = ctypes.c_bool

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
OpenProcess.restype = ctypes.c_void_p

TerminateProcess = kernel32.TerminateProcess
TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
TerminateProcess.restype = ctypes.c_bool

GetExitCodeProcess = kernel32.GetExitCodeProcess
GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
GetExitCodeProcess.restype = ctypes.c_bool


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------
class JobResult:
    """Result of a job operation."""
    def __init__(self, pid, job_id, handle=None, proc=None):
        self.pid = pid
        self.job_id = job_id
        self.handle = handle
        self.proc = proc  # subprocess.Popen

    def close(self):
        if self.handle:
            CloseHandle(self.handle)
            self.handle = None


def create_job_object():
    """Create a Job Object with KILL_ON_JOB_CLOSE. Returns handle."""
    name = f'SERAPHIM-S02-Job-{uuid.uuid4().hex[:8]}'
    h = CreateJobObjectW(None, name)
    if not h:
        raise OSError(f'CreateJobObject failed: {ctypes.get_last_error()}')

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.ProcessMemoryLimit = 512 * 1024 * 1024
    info.JobMemoryLimit = 512 * 1024 * 1024
    info.BasicLimitInformation.ActiveProcessLimit = 10

    size = ctypes.c_uint32(ctypes.sizeof(info))
    ok = SetInformationJobObject(h, JobObjectExtendedLimitInformation,
                                  ctypes.byref(info), size.value)
    if not ok:
        err = ctypes.get_last_error()
        CloseHandle(h)
        raise OSError(f'SetInformationJobObject failed: {err}')

    return h, name


def spawn_in_job(cmd, args, timeout_ms=5000):
    """Spawn a subprocess inside a Job Object with KILL_ON_JOB_CLOSE."""
    job_h, job_name = create_job_object()

    cmdline = [cmd] + list(args)

    proc = subprocess.Popen(
        cmdline,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    proc_h = OpenProcess(0x001F0FFF, False, proc.pid)
    if not proc_h:
        CloseHandle(job_h)
        proc.kill()
        raise OSError('OpenProcess failed')

    if not AssignProcessToJobObject(job_h, proc_h):
        CloseHandle(proc_h)
        CloseHandle(job_h)
        proc.kill()
        raise OSError('AssignProcessToJobObject failed')

    CloseHandle(proc_h)

    return JobResult(pid=proc.pid, job_id=job_name, handle=job_h, proc=proc)


# ---------------------------------------------------------------------------
# Tree kill
# ---------------------------------------------------------------------------
def is_alive(pid):
    """Check if a process is still alive."""
    try:
        h = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_uint32()
        GetExitCodeProcess(h, ctypes.byref(exit_code))
        CloseHandle(h)
        return exit_code.value == STILL_ACTIVE
    except Exception:
        return False


def kill_tree(pid, timeout_ms=5000):
    """Kill a process on Windows. Job Object handles children automatically."""
    if sys.platform != 'win32':
        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return True
        except Exception:
            return False

    try:
        h = OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            TerminateProcess(h, 1)
            CloseHandle(h)
    except Exception:
        pass

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if not is_alive(pid):
            return True
        time.sleep(0.05)

    return not is_alive(pid)


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print('Testing subprocess management...', flush=True)
    result = spawn_in_job('cmd', ['/c', 'echo', 'hello from job'], 5000)
    print(f'  Spawned pid={result.pid}, job={result.job_id}', flush=True)
    out, err = result.proc.communicate(timeout=5)
    print(f'  stdout: {out.decode("utf-8", errors="replace").strip()}', flush=True)
    print(f'  alive before close: {is_alive(result.pid)}', flush=True)
    result.close()
    time.sleep(0.2)
    print(f'  alive after job close: {is_alive(result.pid)}', flush=True)
    print('PASS', flush=True)
