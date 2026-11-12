from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict

from seraphim.contracts.errors import SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.contracts.timestamps import now_utc
from seraphim.core import authority
from seraphim.core.dispatch_store import DispatchStore
from seraphim.core.evidence import CheckSpec, Observation, Verifier
from seraphim.core.requirements import Requirements
from seraphim.core.task_machine import Block, SubmitTask, Verified
from seraphim.core.task_model import (
    TASK_SCOPE,
    CheckOutcome,
    StepStatus,
    TaskStatus,
    VerificationReport,
)
from seraphim.core.task_store import TaskRepository, _report_obj
from seraphim.storage.db import Database
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.registry import ToolRegistry


class VerificationEngine:
    def __init__(self, db: Database, registry: ToolRegistry, root: FsRoot) -> None:
        self.db = db
        self.registry = registry
        self.root = root
        self.tasks = TaskRepository(db)
        self.store = DispatchStore(db)
        self.verifiers: dict[str, Verifier] = {}

    def register(self, kind: str, verifier: Verifier) -> None:
        if kind in self.verifiers:
            raise ValueError("Verifier already registered")
        self.verifiers[kind] = verifier

    def _file(self, check: CheckSpec) -> Observation:
        path = self.root.resolve(check.target, must_exist=False)
        if check.kind == "file_absent":
            return Observation(not path.exists(), True, "filesystem.stat", {"path": check.target, "exists": path.exists()})
        if not path.exists():
            return Observation(False, True, "filesystem.stat", {"path": check.target, "exists": False})
        if check.kind == "file_exists":
            return Observation(True, True, "filesystem.stat", {"path": check.target, "exists": True})
        if not path.is_file() or path.stat().st_size > 1048576:
            return Observation(False, False, "filesystem.read", {"reason": "Not a bounded regular file"})
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        passed = digest == check.expected if check.kind == "file_hash" else data.decode("utf-8") == check.expected
        return Observation(passed, True, "filesystem.read", {"path": check.target, "sha256": digest, "size": len(data)})

    def observe(self, task_id: str, check: CheckSpec) -> Observation:
        try:
            if check.kind == "accepted_step":
                step = self.tasks.load(task_id).task.step(check.target)
                row = self.db.query_one("SELECT 1 FROM verification_authorizations a JOIN verification_runs r ON r.id=a.run_id WHERE a.task_id=? AND a.target=? AND a.consumed=1 AND r.report_json=?", (task_id, check.target, json.dumps(_report_obj(step.report))))
                return Observation(bool(row), True, "verification.accepted", {"step": check.target})
            if check.kind in self.verifiers:
                return self.verifiers[check.kind](check)
            if check.kind in ("file_exists", "file_absent", "file_hash", "file_content"):
                return self._file(check)
            if check.kind in ("tool_result", "command_exit", "test_output"):
                call = next((c for c in self.store.calls(task_id) if c["call_id"] == check.call_id), None)
                if not call or not call["result_json"] or call["status"] not in ("COMPLETED", "FAILED"):
                    return Observation(False, False, "ledger", {"reason": "No completed result"})
                result = json.loads(call["result_json"])
                output = result.get("output") or {}
                if check.kind == "tool_result":
                    passed = result["status"] == "SUCCEEDED"
                elif check.kind == "command_exit":
                    passed = output.get("exit_code") == int(check.expected or "0") and not output.get("timed_out") and not output.get("cancelled")
                else:
                    if output.get("stdout_truncated"):
                        return Observation(False, False, "process.result", {"reason": "Output truncated"})
                    passed = check.expected in output.get("stdout", "") and output.get("exit_code") == 0
                return Observation(passed, True, "ledger:" + check.call_id, {"result_ref": check.call_id,
                    "result_sha256": hashlib.sha256(call["result_json"].encode()).hexdigest()})
        except (OSError, SeraphimError, ValueError, UnicodeError) as exc:
            return Observation(False, True, "verifier.error", {"error": type(exc).__name__})
        return Observation(False, False, "verifier.unavailable", {"kind": check.kind})

    def requirements(self, task_id: str, step_id: str) -> list[CheckSpec]:
        return Requirements(self.root).resolve(self.tasks.load(task_id).task, step_id, self.store.calls(task_id))

    def check(self, task_id: str, target: str, checks: list[CheckSpec]) -> VerificationReport:
        """Persisted diagnostics are intentionally never eligible for Verified."""
        return self._check(task_id, target, checks)

    def _check(self, task_id, target, checks, binding=None) -> VerificationReport:
        outcomes = []
        at = now_utc()
        observations = []
        for spec in checks:
            observed = self.observe(task_id, spec)
            evidence_id = generate_id("artifact")
            observations.append((evidence_id, observed, spec))
            outcomes.append(CheckOutcome(spec.kind + ":" + (spec.target or spec.call_id),
                observed.passed, evidence_id, observed.available, observed.source, at, spec.mandatory))
        report = VerificationReport("core.independent", tuple(outcomes))
        run_id = generate_id("artifact")
        with self.db.transaction() as conn:
            for evidence_id, observed, spec in observations:
                conn.execute("INSERT INTO verification_evidence VALUES(?,?,?,?,?,?)", (
                    evidence_id, task_id, target, observed.source, at,
                    json.dumps({"check": asdict(spec), "observation": asdict(observed)}, sort_keys=True)))
            conn.execute("INSERT INTO verification_runs VALUES(?,?,?,?,?,?)", (
                run_id, task_id, target, at,
                json.dumps([asdict(c) for c in checks], sort_keys=True), json.dumps(_report_obj(report))))
            if binding is not None:
                revision, context, history = binding
                conn.execute("INSERT INTO verification_authorizations(run_id,task_id,target,revision,authority_json,history_json) VALUES(?,?,?,?,?,?)", (run_id, task_id, target, revision, context, history))
        self.store.event(task_id, "VerificationResult", {"target": target, "status": report.status,
                         "evidence": [o.evidence_ref for o in outcomes]})
        return report

    def verify_pending(self, task_id: str) -> VerificationReport:
        record = self.tasks.load(task_id)
        if record.review_required or record.task.status is not TaskStatus.VERIFYING:
            raise ValueError("Verification requires a non-review VERIFYING task")
        target = record.task.pending_verification
        if target == TASK_SCOPE:
            checks = self.requirements(task_id, TASK_SCOPE)
        else:
            checks = self.requirements(task_id, target)
        context = authority.validate(self.db, task_id, self.registry)
        roots = {entry["root"] for entry in json.loads(context)["entries"] if entry["root"]}
        if roots != {os.path.normcase(str(self.root.path))}:
            raise authority.invalid()
        with self.db.transaction() as conn:
            history = authority.history(conn, task_id)
        report = self._check(task_id, target, checks, (record.revision, context, history))
        # Missing evidence/verifier must block, not spend action retry budget.
        if not report.passed and (report.status in ("unverified", "partially_verified")
                                  or any(c.mandatory and not c.available for c in report.checks)):
            self.tasks.save(record, Block("Mandatory independent verification unavailable"),
                            event_type="TaskBlocked", at=now_utc())
        elif not report.passed and target != TASK_SCOPE and record.task.step(target).attempts < record.task.step(target).max_attempts:
            self.tasks.save(record, Block("Verification failed; automatic side-effect retry is not authorized"),
                            event_type="TaskBlocked", at=now_utc())
        else:
            self.tasks.save(record, Verified(target, report), event_type="Verified", at=now_utc())
        return report

    def finish_task(self, task_id: str) -> VerificationReport:
        record = self.tasks.load(task_id)
        if not all(s.status in (StepStatus.SUCCEEDED, StepStatus.SKIPPED) for s in record.task.steps):
            raise ValueError("Task still has incomplete steps")
        self.tasks.save(record, SubmitTask(), event_type="TaskSubmitted", at=now_utc())
        return self.verify_pending(task_id)
