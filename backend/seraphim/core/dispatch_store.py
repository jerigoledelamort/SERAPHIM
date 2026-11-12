"""Durable S24 boundary. No leases and no replay of open/unknown operations.

Ledger writes intentionally use the S17 schema directly so intent/mapping/result
and ledger status commit atomically without nesting Database transactions.
"""
from __future__ import annotations

import json
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.contracts.timestamps import now_utc
from seraphim.storage.db import Database
from seraphim.wings.calls import ToolCall, ToolResult


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _invalid(message: str) -> SeraphimError:
    return SeraphimError(code=ErrorCode.TASK_INVALID, component="core.dispatch_store", safe_message=message)


class DispatchStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _guard(self, conn, task_id: str, *, running: bool = False):
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise _invalid("Task not found.")
        if row["review_required"]:
            raise SeraphimError(code=ErrorCode.TASK_REVIEW_REQUIRED, component="core.dispatch_store",
                                safe_message="Task requires operator review.", task_id=task_id)
        if running and row["status"] != "RUNNING":
            raise _invalid("Dispatch requires a RUNNING task.")
        return row

    def claim(self, task_id: str, owner: str, *, approval: bool = False) -> None:
        with self._db.transaction() as conn:
            row = self._guard(conn, task_id)
            if row["status"] not in (("NEEDS_APPROVAL",) if approval else ("RUNNING",)):
                raise _invalid("Task status does not permit ownership claim")
            if conn.execute("SELECT 1 FROM execution_owners WHERE task_id=?", (task_id,)).fetchone():
                raise _invalid("Task already has an execution owner; recovery must inspect a stale owner")
            conn.execute("INSERT INTO execution_owners VALUES(?,?)", (task_id, owner))

    def release(self, task_id: str, owner: str) -> None:
        self._db.execute("DELETE FROM execution_owners WHERE task_id=? AND owner=?", (task_id, owner))

    def get_state(self, task_id: str) -> dict | None:
        row = self._db.query_one("SELECT state_json FROM execution_state WHERE task_id = ?", (task_id,))
        return json.loads(row["state_json"]) if row else None

    def save_state(self, task_id: str, state: dict) -> None:
        raw = _json(state)
        with self._db.transaction() as conn:
            # Transcript/cursor diagnostics are not dispatch authority. Permit
            # recording why execution stopped under review, but never touch calls.
            if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise _invalid("Task not found.")
            conn.execute("INSERT INTO execution_state(task_id,state_json,updated_at) VALUES(?,?,?) "
                         "ON CONFLICT(task_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at",
                         (task_id, raw, now_utc()))

    def _event(self, conn, task_id: str, type: str, payload: dict) -> None:
        conn.execute("INSERT INTO events(id,timestamp,type,component,task_id,session_id,payload_json) "
                     "VALUES(?,?,?,?,?,?,?)", (generate_id("event"), now_utc(), type,
                     "core.dispatch_store", task_id, "", _json(payload)))

    def event(self, task_id: str, type: str, payload: dict) -> None:
        with self._db.transaction() as conn:
            if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise _invalid("Task not found.")
            self._event(conn, task_id, type, payload)

    def calls(self, task_id: str) -> list[dict]:
        rows = self._db.query("SELECT d.*, l.status AS ledger_status FROM execution_dispatches d "
                              "LEFT JOIN tool_calls l ON l.id=d.ledger_call_id WHERE d.task_id=? "
                              "ORDER BY d.rowid", (task_id,))
        for row in rows:
            row["status"] = row.pop("ledger_status") or row["status"]
        return rows

    def reserve(self, task_id: str, step_id: str, call: ToolCall, sensitivity: str,
                provider_call_id: str | None = None, manifest: dict | None = None,
                owner: str | None = None) -> None:
        raw = _json(call.to_dict())
        with self._db.transaction() as conn:
            self._guard(conn, task_id, running=True)
            self._check_owner(conn, task_id, owner)
            if conn.execute("SELECT 1 FROM execution_dispatches WHERE task_id=? AND status IN "
                            "('RESERVED','WAITING','STARTED','UNKNOWN')", (task_id,)).fetchone():
                raise _invalid("Task already has a pending or unknown operation.")
            if conn.execute("SELECT 1 FROM tool_calls WHERE task_id=? AND status IN ('STARTED','UNKNOWN')",
                            (task_id,)).fetchone():
                raise _invalid("Task already has an open ledger operation.")
            if conn.execute("SELECT 1 FROM execution_dispatches WHERE call_id=?", (call.call_id,)).fetchone():
                raise _invalid("Call has already been dispatched.")
            conn.execute("INSERT INTO execution_dispatches(call_id,task_id,step_id,provider_call_id,call_json,"
                         "status,data_sensitivity,created_at) VALUES(?,?,?,?,?,'RESERVED',?,?)",
                         (call.call_id, task_id, step_id, provider_call_id, raw, sensitivity, now_utc()))
            if manifest is not None:
                conn.execute("UPDATE execution_dispatches SET manifest_json=? WHERE call_id=?",
                             (_json(manifest), call.call_id))

    def waiting(self, call_id: str, approval_id: str) -> None:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT task_id FROM execution_dispatches WHERE call_id=?", (call_id,)).fetchone()
            self._guard(conn, row["task_id"])
            conn.execute("UPDATE execution_dispatches SET status='WAITING',approval_id=? WHERE call_id=? AND status='RESERVED'",
                         (approval_id, call_id))

    def pending(self, task_id: str, approval_id: str) -> dict:
        row = self._db.query_one("SELECT * FROM execution_dispatches WHERE task_id=? AND approval_id=? AND status='WAITING'",
                                 (task_id, approval_id))
        if not row:
            raise _invalid("No persisted operation matches this approval.")
        return row

    def assert_owner(self, task_id: str, owner: str | None) -> None:
        with self._db.transaction() as conn:
            self._check_owner(conn, task_id, owner)

    def _check_owner(self, conn, task_id: str, owner: str | None) -> None:
        current = conn.execute("SELECT owner FROM execution_owners WHERE task_id=?", (task_id,)).fetchone()
        state = conn.execute("SELECT state_json FROM execution_state WHERE task_id=?", (task_id,)).fetchone()
        managed = state and state["state_json"] and json.loads(state["state_json"]).get("limits")
        if (managed and not owner) or (current and current["owner"] != owner) or (owner and not current):
            raise _invalid("Execution ownership does not match")

    def begin(self, call_id: str, *, owner: str | None = None) -> None:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM execution_dispatches WHERE call_id=?", (call_id,)).fetchone()
            self._guard(conn, row["task_id"], running=True)
            self._check_owner(conn, row["task_id"], owner)
            if row["status"] not in ("RESERVED", "WAITING") or self.cancel_requested(row["task_id"], conn):
                raise _invalid("Operation cannot start or cancellation was requested.")
            step = conn.execute("SELECT status FROM task_steps WHERE task_id=? AND step_id=?",
                                (row["task_id"], row["step_id"])).fetchone()
            if not step or step["status"] != "RUNNING":
                raise _invalid("Dispatch requires a RUNNING step.")
            ledger_id = generate_id("call")
            call = json.loads(row["call_json"])
            conn.execute("INSERT INTO tool_calls(id,task_id,step_id,operation,idempotency_key,status,started_at) "
                         "VALUES(?,?,?,?,?,'STARTED',?)", (ledger_id, row["task_id"], row["step_id"],
                         call["tool_id"], call_id, now_utc()))
            conn.execute("UPDATE execution_dispatches SET status='STARTED',ledger_call_id=? WHERE call_id=?",
                         (ledger_id, call_id))
            self._event(conn, row["task_id"], "ToolCallStarted", {"call_id": call_id})

    def finish(self, call_id: str, result: ToolResult, *, unknown: bool = False) -> None:
        raw = _json(result.to_dict())
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM execution_dispatches WHERE call_id=?", (call_id,)).fetchone()
            if row["status"] not in ("RESERVED", "STARTED"):
                raise _invalid("Operation is not open.")
            status = "UNKNOWN" if unknown else ("COMPLETED" if result.status.value == "SUCCEEDED" else "FAILED")
            at = now_utc()
            if row["ledger_call_id"]:
                cursor = conn.execute("UPDATE tool_calls SET status=?,finished_at=?,outcome_ref=?,error_code=? "
                                     "WHERE id=? AND status='STARTED'", (status, at, call_id,
                                     result.error.code if result.error else "", row["ledger_call_id"]))
                if cursor.rowcount != 1:
                    raise _invalid("Ledger outcome was already changed; review required.")
            conn.execute("UPDATE execution_dispatches SET status=?,result_json=?,finished_at=? WHERE call_id=?",
                         (status, raw, at, call_id))
            if unknown:
                conn.execute("UPDATE tasks SET review_required=1,review_reason=?,revision=revision+1,updated_at=? WHERE id=?",
                             ("Tool outcome unknown; do not retry automatically.", at, row["task_id"]))
            self._event(conn, row["task_id"], "ToolCallUnknown" if unknown else "ToolCallCompleted",
                        {"call_id": call_id, "status": status})

    def request_cancel(self, task_id: str) -> bool:
        with self._db.transaction() as conn:
            conn.execute("INSERT INTO execution_state(task_id,updated_at,cancel_requested) VALUES(?,?,1) "
                         "ON CONFLICT(task_id) DO UPDATE SET cancel_requested=1", (task_id, now_utc()))
            return bool(conn.execute("SELECT 1 FROM execution_dispatches WHERE task_id=? AND status='STARTED'",
                                     (task_id,)).fetchone())

    def cancel_requested(self, task_id: str, conn=None) -> bool:
        row = self._db.query_one("SELECT cancel_requested FROM execution_state WHERE task_id=?",
                                 (task_id,), connection=conn)
        return bool(row and row["cancel_requested"])
