from __future__ import annotations

import hashlib
import json

from seraphim.contracts.ids import generate_id
from seraphim.contracts.timestamps import now_utc
from seraphim.storage.db import Database


class RecoveryEngine:
    """Transactional inspection; never invokes tools or steals ownership."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def inspect(self, task_id: str) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise ValueError("Task not found")
            cursor = conn.execute("SELECT * FROM execution_state WHERE task_id=?", (task_id,)).fetchone()
            state = json.loads(cursor["state_json"]) if cursor and cursor["state_json"] else {}
            calls = [dict(c) for c in conn.execute("SELECT * FROM execution_dispatches WHERE task_id=? ORDER BY rowid", (task_id,))]
            owner = conn.execute("SELECT owner FROM execution_owners WHERE task_id=?", (task_id,)).fetchone()
            ledger = [dict(c) for c in conn.execute("SELECT * FROM tool_calls WHERE task_id=?", (task_id,))]
            uncertain = any(c["status"] in ("STARTED", "UNKNOWN") for c in ledger) or any(
                c["status"] in ("RESERVED", "STARTED", "UNKNOWN") for c in calls)
            if owner:
                decision = "owned_inspection_only"
            elif uncertain or row["review_required"] or state.get("approval_accounting_pending"):
                decision = "review"
                if uncertain and not row["review_required"]:
                    conn.execute("UPDATE tasks SET review_required=1,review_reason=?,revision=revision+1,updated_at=? WHERE id=?",
                                 ("Recovery found open intent; no replay", now_utc(), task_id))
            elif row["status"] == "NEEDS_APPROVAL" and state.get("phase") == "approval_pending":
                decision = "approval_pending"
            elif row["status"] == "VERIFYING":
                decision = "verification_only"
            elif state.get("phase") == "ready" and row["status"] in ("RUNNING", "PAUSED"):
                decision = "safe_cursor"
            else:
                decision = "inspect_only"
            payload = {
                "version": 1, "task_id": task_id,
                "revision": conn.execute("SELECT revision FROM tasks WHERE id=?", (task_id,)).fetchone()["revision"],
                "plan": json.loads(row["plan_json"]), "status": row["status"], "cursor": state,
                "context_digest": hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest(),
                "calls": calls, "ledger": ledger, "owner": dict(owner) if owner else None,
                "decision": decision,
            }
            for key, sql in (
                ("events", "SELECT id,type FROM events WHERE task_id=? ORDER BY rowid DESC LIMIT 16"),
                ("evidence", "SELECT id,source FROM verification_evidence WHERE task_id=?"),
                ("approvals", "SELECT id,status FROM approvals WHERE task_id=?"),
            ):
                payload[key] = [dict(item) for item in conn.execute(sql, (task_id,))]
            conn.execute("INSERT INTO recovery_checkpoints VALUES(?,?,?,?)",
                         (generate_id("checkpoint"), task_id, now_utc(), json.dumps(payload, sort_keys=True)))
        return payload
