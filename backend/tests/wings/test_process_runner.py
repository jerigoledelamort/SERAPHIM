# WINGS process runner (S22). Offline: only the current Python interpreter is executed.

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.process_runner import MAX_OUTPUT_BYTES, CancelToken, build_env, run_process

PYTHON_DIR = os.path.dirname(sys.executable)
PY_ENV = {"PATH": PYTHON_DIR + os.pathsep + os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
PY = "python"
ALLOWED = ("python",)


@pytest.fixture
def sandbox(tmp_path: Path) -> FsRoot:
    return FsRoot(tmp_path)


def _run(sandbox: FsRoot, *argv: str, **kwargs: object):
    return run_process([PY, *argv], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV, **kwargs)  # type: ignore[arg-type]


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
    return str(pid) in out


class TestExitStatus:
    def test_success_reports_zero_exit(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "print('ok')")
        assert result.exit_code == 0
        assert result.stdout.strip() == "ok"
        assert not result.timed_out and not result.cancelled

    def test_nonzero_exit_is_reported_not_raised(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "import sys; sys.exit(3)")
        assert result.exit_code == 3
        assert not result.timed_out


class TestArgumentsAreNotShell:
    @pytest.mark.parametrize("payload", ["a&calc.exe", "x|y", "a;b", "$(whoami)", "%PATH%", "a b", "(c)"])
    def test_metacharacters_are_literal_argument(self, sandbox: FsRoot, payload: str) -> None:
        result = _run(sandbox, "-c", "import sys; print(sys.argv[1])", payload)
        assert result.stdout.strip() == payload

    def test_executable_must_be_bare_name(self, sandbox: FsRoot) -> None:
        for bad in ("C:\\Windows\\System32\\cmd.exe", "../evil", "bin/tool"):
            with pytest.raises(SeraphimError) as exc:
                run_process([bad], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV)
            assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_unknown_executable_is_refused(self, sandbox: FsRoot) -> None:
        with pytest.raises(SeraphimError) as exc:
            run_process(["definitely-not-a-real-binary-xyz"], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV)
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_executable_outside_allowlist_is_refused_before_launch(self, sandbox: FsRoot) -> None:
        marker = Path(sandbox.path) / "ran.txt"
        with pytest.raises(SeraphimError) as exc:
            run_process(
                [PY, "-c", f"open({str(marker)!r},'w').write('x')"],
                cwd=sandbox, allowed=("other-tool",), env_source=PY_ENV,
            )
        assert exc.value.code == ErrorCode.VALIDATION_FAILED
        assert not marker.exists()

    def test_empty_allowlist_refuses_every_executable(self, sandbox: FsRoot) -> None:
        with pytest.raises(SeraphimError) as exc:
            run_process([PY, "-c", "pass"], cwd=sandbox, allowed=(), env_source=PY_ENV)
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_argv_limits_are_enforced(self, sandbox: FsRoot) -> None:
        with pytest.raises(SeraphimError):
            run_process([PY, *(["x"] * 65)], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV)
        with pytest.raises(SeraphimError):
            run_process([PY, "a" * 2000], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV)


class TestCwdAndEnv:
    def test_runs_inside_sandbox_cwd(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "import os; print(os.getcwd())")
        assert Path(result.stdout.strip()).resolve() == sandbox.path.resolve()

    def test_environment_is_allowlisted(self, sandbox: FsRoot, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERAPHIM_TEST_SECRET_VALUE", "should-not-leak")
        result = _run(sandbox, "-c", "import os; print(os.environ.get('SERAPHIM_TEST_SECRET_VALUE'))")
        assert result.stdout.strip() == "None"

    def test_build_env_keeps_only_allowlisted_keys(self) -> None:
        env = build_env({"PATH": "p", "AWS_SECRET_ACCESS_KEY": "x", "HOME": "h"})
        assert env == {"PATH": "p"}

    def test_env_name_must_be_identifier(self) -> None:
        with pytest.raises(SeraphimError):
            build_env({"PATH": "p"}, {"BAD NAME": "v"})

    def test_secret_in_output_is_redacted(self, sandbox: FsRoot) -> None:
        script = "print('token=abcdef1234567890abcdef')"
        result = _run(sandbox, "-c", script)
        assert "abcdef1234567890abcdef" not in result.stdout
        assert "REDACTED" in result.stdout

    def test_known_api_key_pattern_is_redacted_in_stderr(self, sandbox: FsRoot) -> None:
        script = "import sys; sys.stderr.write('key sk-abcdefghijklmnopqrstuvwx\\n')"
        result = _run(sandbox, "-c", script)
        assert "sk-abcdefghijklmnopqrstuvwx" not in result.stderr


class TestOutputLimits:
    def test_huge_output_is_truncated(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "import sys; sys.stdout.write('a' * 500000)")
        assert result.stdout_truncated is True
        assert len(result.stdout) <= MAX_OUTPUT_BYTES
        assert result.exit_code == 0

    def test_stderr_is_bounded_too(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "import sys; sys.stderr.write('b' * 500000)")
        assert result.stderr_truncated is True
        assert len(result.stderr) <= MAX_OUTPUT_BYTES


class TestTimeoutAndCancel:
    def test_timeout_stops_process(self, sandbox: FsRoot) -> None:
        result = _run(sandbox, "-c", "import time; time.sleep(60)", timeout_seconds=1)
        assert result.timed_out is True
        assert result.exit_code is None

    def test_timeout_kills_grandchild_process(self, sandbox: FsRoot) -> None:
        grandchild = "import time; time.sleep(60)"
        parent = (
            "import subprocess, sys, time\n"
            f"p = subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
            "open('child.pid', 'w').write(str(p.pid))\n"
            "time.sleep(60)\n"
        )
        result = _run(sandbox, "-c", parent, timeout_seconds=2)
        assert result.timed_out is True
        child_pid = int((Path(sandbox.path) / "child.pid").read_text())
        assert not _alive(child_pid), "grandchild must not survive the timeout"

    def test_cancel_stops_process(self, sandbox: FsRoot) -> None:
        token = CancelToken()
        timer = threading.Timer(0.5, token.cancel)
        timer.start()
        try:
            result = _run(sandbox, "-c", "import time; time.sleep(60)", cancel=token, timeout_seconds=30)
        finally:
            timer.cancel()
        assert result.cancelled is True
        assert result.exit_code is None
        assert result.duration_ms < 15_000

    def test_timeout_bounds_are_validated(self, sandbox: FsRoot) -> None:
        for bad in (0, 121, True, "5"):
            with pytest.raises(SeraphimError):
                run_process([PY, "-c", "pass"], cwd=sandbox, allowed=ALLOWED, env_source=PY_ENV, timeout_seconds=bad)  # type: ignore[arg-type]
