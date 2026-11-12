"""CORE durable dispatch boundary: approval, intent, invocation, result.

Open/unknown operations are never replayed. The database reservation, not a
process-local lock, serializes dispatch across orchestrator instances.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from seraphim.aegis.gate import make_gate
from seraphim.aegis.policy import PolicyEngine
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.timestamps import now_utc
from seraphim.core import authority
from seraphim.core.approval import ApprovalRequest, ApprovalService
from seraphim.core.dispatch_store import DispatchStore
from seraphim.core.task_machine import (
    Approve,
    Block,
    Cancel,
    RejectApproval,
    RequestApproval,
    StartStep,
)
from seraphim.core.task_model import StepStatus, TaskStatus
from seraphim.core.task_store import TaskRepository
from seraphim.storage.db import Database
from seraphim.wings.calls import CallStatus, ToolCall, ToolError, ToolResult
from seraphim.wings.registry import PolicyGate, ToolRegistry

COMPONENT = "core.orchestration"
T = TaskStatus


@dataclass(frozen=True)
class StepOutcome:
    status: str
    approval: ApprovalRequest | None = None
    result: ToolResult | None = None


class StepOrchestrator:
    def __init__(self, db: Database, registry: ToolRegistry, engine: PolicyEngine, *, actor: str) -> None:
        self._tasks = TaskRepository(db)
        self._approvals = ApprovalService(db)
        self._store = DispatchStore(db)
        self._registry = registry
        self._confirmed: set[str] = set()
        self._engine = engine
        self._actor = actor
        self.execution_owner: str | None = None

    def _gate(self, sensitivity: str) -> PolicyGate:
        return make_gate(self._engine, actor=self._actor, data_sensitivity=sensitivity,
                         confirmed=lambda call: call.call_id in self._confirmed,
                         registry=self._registry)

    def run_step(self, task_id: str, step_id: str, call: ToolCall, *, explanation: str,
                 resource: str, risk: str, data_sensitivity: str = "internal",
                 timeout_seconds: float | None = None) -> StepOutcome:
        return self.dispatch(task_id, step_id, call, explanation=explanation, resource=resource,
                             risk=risk, data_sensitivity=data_sensitivity, timeout_seconds=timeout_seconds)

    def dispatch(self, task_id: str, step_id: str, call: ToolCall, *, explanation: str = "",
                 resource: str = "", risk: str = "low", data_sensitivity: str = "internal",
                 timeout_seconds: float | None = None, provider_call_id: str | None = None) -> StepOutcome:
        record = self._tasks.load(task_id)
        if record.task.status is not T.RUNNING or self._store.cancel_requested(task_id):
            raise self._invalid("No new call may start: task is not running or cancel is pending.")
        if (call.task_id and call.task_id != task_id) or (call.step_id and call.step_id != step_id):
            raise self._invalid("Tool call task/step does not match dispatch target.")
        # Canonical copy also prevents caller/provider mutation of persisted arguments.
        call = ToolCall(**json.loads(json.dumps({**call.to_dict(), "task_id": task_id, "step_id": step_id})))
        authority.bind(self._tasks._db, task_id, self._registry)
        preflight = self._registry.validate(call)
        if preflight is not None:
            return StepOutcome(preflight.status.value, result=preflight)
        decision = self._gate(data_sensitivity)(self._registry.manifest(call.tool_id), call)
        if not decision.allowed and decision.outcome != "ASK_USER":
            result = ToolResult(call.call_id, call.tool_id, CallStatus.REJECTED, 0,
                                error=ToolError(ErrorCode.TOOL_PERMISSION_DENIED, decision.reason))
            return StepOutcome(result.status.value, result=result)
        step = record.task.step(step_id)
        self._store.reserve(task_id, step_id, call, data_sensitivity, provider_call_id,
                            manifest=self._registry.manifest(call.tool_id).to_dict(), owner=self.execution_owner)
        binding = authority.operation(self._registry, call, data_sensitivity)
        self._tasks._db.execute("UPDATE execution_dispatches SET authority_json=? WHERE call_id=?", (binding, call.call_id))
        if step.status is StepStatus.RUNNING:
            if decision.outcome == "ASK_USER":
                record = self._tasks.save(record, RequestApproval(step_id), event_type="ApprovalRequired", at=now_utc())
        else:
            record = self._tasks.save(record, StartStep(step_id, needs_approval=decision.outcome == "ASK_USER"),
                                      event_type="StepStarted", at=now_utc())
        if record.task.status is T.NEEDS_APPROVAL:
            approval = self._approvals.request(task_id=task_id, step_id=step_id, tool_id=call.tool_id,
                arguments=call.arguments, explanation=explanation or "Approve tool operation",
                resource=resource, risk=risk, authority_digest=authority.digest(binding))
            self._store.waiting(call.call_id, approval.id)
            return StepOutcome(T.NEEDS_APPROVAL.value, approval=approval)
        return self._execute(task_id, call, data_sensitivity, timeout_seconds)

    def approve(self, task_id: str, step_id: str, approval_id: str, call: ToolCall,
                *, data_sensitivity: str = "internal", timeout_seconds: float | None = None) -> StepOutcome:
        record = self._tasks.load(task_id)
        if record.task.status is not T.NEEDS_APPROVAL or record.task.pending_approval_step != step_id:
            raise self._invalid("Approval requires the pending task step.")
        self._store.assert_owner(task_id, self.execution_owner)
        state = self._store.get_state(task_id)
        if state and state.get("limits") and not self.execution_owner:
            raise self._invalid("Executor-managed approval requires executor ownership and budget enforcement")
        persisted = self._store.pending(task_id, approval_id)
        # Keep S23 compatibility: a mismatching operation records the user's grant,
        # but does not consume it or mutate task state or dispatch a replacement.
        self.validate_approval_authority(task_id, approval_id)
        self._approvals.decide(approval_id, approve=True)
        exact = ToolCall(**json.loads(persisted["call_json"]))
        if (call.call_id != exact.call_id or call.tool_id != exact.tool_id or call.arguments != exact.arguments
                or (call.task_id and call.task_id != task_id) or (call.step_id and call.step_id != step_id)):
            raise self._invalid("Approval cannot replace the persisted operation.")
        self._approvals.consume(approval_id, tool_id=exact.tool_id, arguments=exact.arguments,
                                task_id=task_id, step_id=step_id, authority_digest=authority.digest(persisted["authority_json"]))
        record = self._tasks.save(record, Approve(step_id), event_type="StepApproved", at=now_utc())
        if record.task.step(step_id).status is not StepStatus.RUNNING:
            self._tasks.save(record, StartStep(step_id), event_type="StepStarted", at=now_utc())
        self._confirmed.add(exact.call_id)
        try:
            # Sensitivity comes from the durable request, never the approval caller.
            return self._execute(task_id, exact, persisted["data_sensitivity"], timeout_seconds)
        finally:
            self._confirmed.discard(exact.call_id)

    def validate_approval_authority(self, task_id: str, approval_id: str) -> None:
        authority.validate(self._tasks._db, task_id, self._registry)
        row = self._store.pending(task_id, approval_id)
        call = ToolCall(**json.loads(row["call_json"]))
        if not row["authority_json"] or row["authority_json"] != authority.operation(self._registry, call, row["data_sensitivity"]):
            raise authority.invalid()

    def deny(self, task_id: str, step_id: str, approval_id: str) -> StepOutcome:
        record = self._tasks.load(task_id)
        pending = self._store.pending(task_id, approval_id)
        if pending["step_id"] != step_id:
            raise self._invalid("Approval belongs to another step.")
        self._approvals.decide(approval_id, approve=False)
        record = self._tasks.save(record, RejectApproval(step_id), event_type="StepDenied", at=now_utc())
        return StepOutcome(record.task.status.value, approval=self._approvals.load(approval_id))

    def cancel(self, task_id: str, reason: str) -> TaskStatus:
        if self._store.request_cancel(task_id):
            return self._tasks.load(task_id).task.status
        record = self._tasks.load(task_id)
        if record.task.status in (T.READY, T.RUNNING, T.VERIFYING, T.RETRYING, T.PAUSED, T.NEEDS_APPROVAL):
            record = self._tasks.save(record, Cancel(reason), event_type="TaskCancelled", at=now_utc())
        return record.task.status

    def _execute(self, task_id: str, call: ToolCall, data_sensitivity: str,
                 timeout_seconds: float | None) -> StepOutcome:
        pinned = self._registry.pinned()
        authority.validate(self._tasks._db, task_id, pinned)
        row = self._tasks._db.query_one("SELECT authority_json FROM execution_dispatches WHERE call_id=?", (call.call_id,))
        if not row or row["authority_json"] != authority.operation(pinned, call, data_sensitivity):
            raise authority.invalid()
        self._store.begin(call.call_id, owner=self.execution_owner)
        try:
            result = pinned.call(call, policy=make_gate(self._engine, actor=self._actor,
                data_sensitivity=data_sensitivity, confirmed=lambda c: c.call_id in self._confirmed,
                registry=pinned), timeout_seconds=timeout_seconds)
        except BaseException as exc:
            result = ToolResult(call.call_id, call.tool_id, CallStatus.FAILED, 0,
                                error=ToolError(ErrorCode.INTERNAL_ERROR, "Tool invocation outcome is unknown."))
            self._store.finish(call.call_id, result, unknown=True)
            self._block_unknown(task_id)
            if not isinstance(exc, Exception):
                raise
            return StepOutcome(result.status.value, result=result)
        # Any post-invocation failure is uncertain: provider exceptions and invalid
        # output can happen after a write. A pre-invocation rejection is known safe.
        unknown = result.status not in (CallStatus.SUCCEEDED, CallStatus.REJECTED)
        try:
            json.dumps(result.to_dict(), allow_nan=False)
            if result.call_id != call.call_id or result.tool_id != call.tool_id:
                raise ValueError("Mismatching tool result")
        except (TypeError, ValueError):
            result = ToolResult(call.call_id, call.tool_id, CallStatus.FAILED, 0,
                                error=ToolError(ErrorCode.TOOL_SCHEMA_INVALID,
                                                "Tool output is not a valid serializable result; outcome unknown."))
            unknown = True
        self._store.finish(call.call_id, result, unknown=unknown)
        if unknown:
            self._block_unknown(task_id)
        elif self._store.cancel_requested(task_id):
            record = self._tasks.load(task_id)
            if record.task.status is T.RUNNING:
                self._tasks.save(record, Cancel("cancel requested"), event_type="TaskCancelled", at=now_utc())
            return StepOutcome("CANCEL_AFTER_CALL", result=result)
        return StepOutcome(result.status.value, result=result)

    def _block_unknown(self, task_id: str) -> None:
        record = self._tasks.load(task_id)
        if record.task.status in (T.RUNNING, T.NEEDS_APPROVAL, T.PAUSED, T.RETRYING, T.VERIFYING):
            self._tasks.save(record, Block("tool call outcome unknown; operator review required"),
                             event_type="TaskBlocked", at=now_utc())

    @staticmethod
    def _invalid(message: str) -> SeraphimError:
        return SeraphimError(code=ErrorCode.TASK_INVALID, component=COMPONENT, safe_message=message)


__all__ = ["StepOrchestrator", "StepOutcome"]
