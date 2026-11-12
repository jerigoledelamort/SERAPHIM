from __future__ import annotations

import json
from pathlib import Path

from seraphim.aegis import PolicyEngine, PolicyRule, PolicySet
from seraphim.compass.router import Candidate
from seraphim.core.execution_model import ExecutionLimits
from seraphim.core.executor import Executor
from seraphim.core.orchestration import StepOrchestrator
from seraphim.core.task_model import StepStatus, TaskStatus
from seraphim.core.verification import VerificationEngine
from seraphim.model_layer.capabilities import ProviderCapabilities
from seraphim.model_layer.fake import FakeProvider, FakeTurn
from seraphim.model_layer.health import HealthStatus
from seraphim.storage import Database, MigrationRunner
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.fs_tools import register_fs_tools
from seraphim.wings.registry import ToolRegistry


class OfflineRuntime:
    """Explicit local-only composition. Script is data, never imported code."""

    def __init__(self, root: Path, sandbox: Path, script: Path | None = None, policy: str = "allow") -> None:
        root, sandbox = root.resolve(), sandbox.resolve()
        if root == sandbox or root in sandbox.parents or sandbox in root.parents:
            raise ValueError("Database root and sandbox must be separate directories")
        sandbox.mkdir(parents=True, exist_ok=True)
        self.db = Database.open(root, environ={})
        MigrationRunner(self.db).run()
        registry = ToolRegistry()
        fs = FsRoot(sandbox)
        register_fs_tools(registry, fs)
        turns = []
        if script:
            if script.stat().st_size > 131072:
                raise ValueError("Script exceeds size budget")
            data = json.loads(script.read_text(encoding="utf-8"))
            if not isinstance(data, list) or len(data) > 32:
                raise ValueError("Script must contain at most 32 turns")
            turns = [FakeTurn(**turn) for turn in data]
        rules = [PolicyRule(rule_id="aegis.global.offline" if policy == "ask" else "aegis.user.offline",
                            source="global" if policy == "ask" else "user", outcome={
            "allow": "ALLOW", "deny": "DENY", "ask": "ASK_USER"}[policy], tool_pattern="tool.fs.*",
            waived_when_confirmed=policy == "ask")]
        if policy == "ask":
            rules.append(PolicyRule(rule_id="aegis.user.confirmed", source="user", outcome="ALLOW", tool_pattern="tool.fs.*"))
        provider = FakeProvider(capabilities=ProviderCapabilities(tool_calls=True), script=turns)
        orchestrator = StepOrchestrator(self.db, registry, PolicyEngine(PolicySet(tuple(rules))), actor="offline-cli")
        self.executor = Executor(self.db, registry, orchestrator,
                                 [Candidate("fake-model", provider, external=False, health=HealthStatus.ONLINE)],
                                 limits=ExecutionLimits())
        self.verification = VerificationEngine(self.db, registry, fs)

    def run(self, task_id: str) -> None:
        for _ in range(64):
            task = self.executor.tasks.load(task_id).task
            if task.status is TaskStatus.VERIFYING:
                self.verification.verify_pending(task_id)
            elif task.status is TaskStatus.RUNNING:
                if all(step.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for step in task.steps):
                    self.verification.finish_task(task_id)
                else:
                    self.executor.run(task_id)
            else:
                return
        raise ValueError("Offline driver transition budget exhausted")
