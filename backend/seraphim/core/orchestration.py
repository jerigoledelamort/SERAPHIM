# CORE step orchestration (S23): gates a risky tool call behind a user approval and
# keeps cancellation honest. Every state change goes through TaskRepository.save() and
# task_machine.transition(); the tool itself runs only through ToolRegistry.call().
#
# Cancel is requested, not forced: a call that has already started runs to its end, and
# the task moves to CANCELLED only after that call returns. No new call starts after a
# cancel request.

from __future__ import annotations

import threading
from dataclasses import dataclass

from seraphim.aegis.gate import make_gate
from seraphim.aegis.policy import PolicyDecision, PolicyEngine
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.timestamps import now_utc
from seraphim.core.approval import ApprovalRequest, ApprovalService
from seraphim.core.task_machine import Approve, Block, Cancel, RejectApproval, StartStep
from seraphim.core.task_model import TaskStatus
from seraphim.core.task_store import TaskRepository
from seraphim.storage.db import Database
from seraphim.wings.calls import CallStatus, ToolCall, ToolResult
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
        self._registry = registry
        self._confirmed: set[str] = set()
        self._engine = engine
        self._actor = actor
        self._lock = threading.Lock()
        self._in_flight: set[str] = set()
        self._cancel_requested: set[str] = set()

    def _gate(self, sensitivity: str) -> PolicyGate:
        return make_gate(
            self._engine,
            actor=self._actor,
            data_sensitivity=sensitivity,
            confirmed=lambda call: call.call_id in self._confirmed,
        )

    def run_step(
        self,
        task_id: str,
        step_id: str,
        call: ToolCall,
        *,
        explanation: str,
        resource: str,
        risk: str,
        data_sensitivity: str = "internal",
    ) -> StepOutcome:
        """Start a step. Risky steps stop at NEEDS_APPROVAL and wait for a decision."""
        record = self._tasks.load(task_id)
        self._reject_if_cancel_pending(record.task.status)
        decision = self._decide(call, data_sensitivity)
        if not decision.allowed and decision.outcome != "ASK_USER":
            return self._execute(task_id, step_id, call, data_sensitivity)
        needs_approval = decision.outcome == "ASK_USER"
        record = self._tasks.save(
            record, StartStep(step_id, needs_approval=needs_approval), event_type="StepStarted", at=now_utc()
        )
        if record.task.status is T.NEEDS_APPROVAL:
            approval = self._approvals.request(
                task_id=task_id,
                step_id=step_id,
                tool_id=call.tool_id,
                arguments=call.arguments,
                explanation=explanation,
                resource=resource,
                risk=risk,
            )
            return StepOutcome(status=T.NEEDS_APPROVAL.value, approval=approval)
        return self._execute(task_id, step_id, call, data_sensitivity)

    def approve(
        self, task_id: str, step_id: str, approval_id: str, call: ToolCall, *, data_sensitivity: str = "internal"
    ) -> StepOutcome:
        """Record the user's grant, spend it for this exact call, then run the call."""
        record = self._tasks.load(task_id)
        if record.task.status is not T.NEEDS_APPROVAL:
            raise SeraphimError(
                code=ErrorCode.TASK_INVALID,
                component=COMPONENT,
                safe_message=f"Approval requires NEEDS_APPROVAL, task is {record.task.status.value}.",
                task_id=task_id,
            )
        self._approvals.decide(approval_id, approve=True)
        record = self._tasks.save(record, Approve(step_id), event_type="StepApproved", at=now_utc())
        self._approvals.consume(
            approval_id,
            tool_id=call.tool_id,
            arguments=call.arguments,
            task_id=task_id,
            step_id=step_id,
        )
        self._confirmed.add(call.call_id)
        try:
            return self._execute(task_id, step_id, call, data_sensitivity)
        finally:
            self._confirmed.discard(call.call_id)

    def deny(self, task_id: str, step_id: str, approval_id: str) -> StepOutcome:
        record = self._tasks.load(task_id)
        self._approvals.decide(approval_id, approve=False)
        record = self._tasks.save(record, RejectApproval(step_id), event_type="StepDenied", at=now_utc())
        return StepOutcome(status=record.task.status.value, approval=self._approvals.load(approval_id))

    def cancel(self, task_id: str, reason: str) -> TaskStatus:
        """Cancel the task now if no call is in flight; otherwise mark the request for later."""
        with self._lock:
            self._cancel_requested.add(task_id)
            if task_id in self._in_flight:
                return self._tasks.load(task_id).task.status
            record = self._tasks.load(task_id)
            if record.task.status in (T.READY, T.RUNNING, T.VERIFYING, T.RETRYING, T.PAUSED, T.NEEDS_APPROVAL):
                record = self._tasks.save(record, Cancel(reason), event_type="TaskCancelled", at=now_utc())
            return record.task.status

    def _execute(self, task_id: str, step_id: str, call: ToolCall, data_sensitivity: str) -> StepOutcome:
        with self._lock:
            if task_id in self._cancel_requested:
                record = self._tasks.load(task_id)
                if record.task.status not in (T.CANCELLED, T.BLOCKED, T.FAILED, T.SUCCEEDED):
                    self._tasks.save(record, Cancel("cancel requested"), event_type="TaskCancelled", at=now_utc())
                return StepOutcome(status=CallStatus.CANCELLED.value)
            self._in_flight.add(task_id)
        try:
            result = self._registry.call(call, policy=self._gate(data_sensitivity))
        finally:
            with self._lock:
                self._in_flight.discard(task_id)
        if task_id in self._cancel_requested:
            record = self._tasks.load(task_id)
            if record.task.status not in (T.CANCELLED, T.BLOCKED, T.FAILED, T.SUCCEEDED):
                self._tasks.save(record, Cancel("cancel requested"), event_type="TaskCancelled", at=now_utc())
            return StepOutcome(status="CANCEL_AFTER_CALL", result=result)
        if result.error is not None and result.error.code == ErrorCode.TOOL_TIMEOUT:
            record = self._tasks.load(task_id)
            if record.task.status is T.RUNNING:
                self._tasks.save(
                    record, Block("tool call timed out with unknown outcome"),
                    event_type="TaskBlocked", at=now_utc(),
                )
        return StepOutcome(status=result.status.value, result=result)

    def _decide(self, call: ToolCall, data_sensitivity: str) -> PolicyDecision:
        return self._gate(data_sensitivity)(self._registry.manifest(call.tool_id), call)

    def _reject_if_cancel_pending(self, status: TaskStatus) -> None:
        if status in (T.CANCELLED, T.BLOCKED, T.FAILED, T.SUCCEEDED):
            raise SeraphimError(
                code=ErrorCode.TASK_INVALID,
                component=COMPONENT,
                safe_message=f"No new call may start: task is {status.value}.",
            )


__all__ = ["StepOrchestrator", "StepOutcome"]
