# WINGS process tool (S22): runs one allowlisted executable with an argv list inside the
# sandbox root. Arbitrary shell execution is not offered: it would need its own
# high-risk permission category and is out of scope for this stage.

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.manifest import ToolManifest
from seraphim.wings.process_runner import MAX_TIMEOUT_SECONDS, run_process

_OUTPUT_OBJECT = {"type": "object"}


def _manifest() -> ToolManifest:
    return ToolManifest(
        id="tool.process.run",
        description="Run one allowlisted executable with argv inside the sandbox directory.",
        input_schema={
            "type": "object",
            "properties": {
                "executable": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "timeout_seconds": {"type": "integer"},
            },
            "required": ["executable"],
        },
        output_schema=_OUTPUT_OBJECT,
        capabilities=("process.run",),
        risk="high",
        side_effects="external",
        permissions=("process.run",),
        timeout_seconds=MAX_TIMEOUT_SECONDS,
        supports_cancellation=False,
        idempotency="unknown",
        source="core",
        version="1.0",
    )


PROCESS_MANIFEST = _manifest()


class ProcessToolProvider:
    def __init__(self, sandbox: FsRoot, allowed_executables: Collection[str]) -> None:
        self._sandbox = sandbox
        self._allowed = frozenset(allowed_executables)

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
        result = run_process(
            [arguments["executable"], *arguments.get("argv", [])],
            cwd=self._sandbox,
            allowed=self._allowed,
            timeout_seconds=arguments.get("timeout_seconds", 30),
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
            "timed_out": result.timed_out,
            "cancelled": result.cancelled,
            "duration_ms": result.duration_ms,
        }
