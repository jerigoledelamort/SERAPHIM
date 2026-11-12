# CORE approval service (S23): asks the user before a risky tool call runs.
#
# An approval is bound to one operation by a fingerprint of (tool, arguments, task,
# step). It is valid once, only before expires_at, and only for that fingerprint.
# No answer is not consent: a PENDING request never authorises anything, and an
# expired request is never revived.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id, validate_id
from seraphim.contracts.sanitization import sanitize_dict
from seraphim.contracts.timestamps import now_utc, validate_timestamp
from seraphim.storage.db import Database

COMPONENT = "core.approval"

PENDING = "PENDING"
APPROVED = "APPROVED"
DENIED = "DENIED"
EXPIRED = "EXPIRED"
CONSUMED = "CONSUMED"

DEFAULT_TTL_SECONDS = 300
MIN_TTL_SECONDS = 10
MAX_TTL_SECONDS = 3600
PREVIEW_MAX_CHARS = 500


def _err(code: str, message: str, *, task_id: str = "") -> SeraphimError:
    return SeraphimError(code=code, component=COMPONENT, safe_message=message, task_id=task_id)


def fingerprint(*, tool_id: str, arguments: dict[str, Any], task_id: str, step_id: str, authority_digest: str = "") -> str:
    binding = {"tool_id": tool_id, "arguments": arguments, "task_id": task_id, "step_id": step_id}
    if authority_digest:
        binding["authority_digest"] = authority_digest
    canonical = json.dumps(
        binding,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def preview(arguments: dict[str, Any]) -> dict[str, str]:
    """Argument preview for the user: redacted and length-limited, never the raw dict."""
    clean = sanitize_dict({str(k): v for k, v in arguments.items()})
    out: dict[str, str] = {}
    for key, value in clean.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        out[key] = text if len(text) <= PREVIEW_MAX_CHARS else text[:PREVIEW_MAX_CHARS] + "…"
    return out


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    task_id: str
    step_id: str
    tool_id: str
    fingerprint: str
    explanation: str
    preview: dict[str, str]
    resource: str
    risk: str
    status: str
    created_at: str
    expires_at: str
    decided_at: str
    consumed_at: str


def _ttl_seconds(ttl: int) -> int:
    if not isinstance(ttl, int) or isinstance(ttl, bool):
        raise _err(ErrorCode.VALIDATION_FAILED, "Approval TTL must be an integer number of seconds.")
    if not MIN_TTL_SECONDS <= ttl <= MAX_TTL_SECONDS:
        raise _err(
            ErrorCode.VALIDATION_FAILED,
            f"Approval TTL must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS} seconds.",
        )
    return ttl


def _shift(at: str, seconds: int) -> str:
    base = datetime.fromisoformat(at.replace("Z", "+00:00"))
    shifted = (base + timedelta(seconds=seconds)).astimezone(UTC)
    return shifted.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ApprovalService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def request(
        self,
        *,
        task_id: str,
        step_id: str,
        tool_id: str,
        arguments: dict[str, Any],
        explanation: str,
        resource: str,
        risk: str,
        authority_digest: str = "",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        at: str | None = None,
    ) -> ApprovalRequest:
        if not explanation:
            raise _err(ErrorCode.VALIDATION_FAILED, "Approval needs an explanation.", task_id=task_id)
        ttl = _ttl_seconds(ttl_seconds)
        created = at or now_utc()
        validate_timestamp(created)
        request_id = generate_id("approval")
        fp = fingerprint(tool_id=tool_id, arguments=arguments, task_id=task_id, step_id=step_id, authority_digest=authority_digest)
        view = preview(arguments)
        row = {
            "id": request_id,
            "task_id": task_id,
            "step_id": step_id,
            "tool_id": tool_id,
            "fingerprint": fp,
            "authority_digest": authority_digest,
            "explanation": explanation,
            "preview_json": json.dumps(view, ensure_ascii=False, sort_keys=True),
            "resource": resource,
            "risk": risk,
            "status": PENDING,
            "created_at": created,
            "expires_at": _shift(created, ttl),
        }
        self._db.insert_row("approvals", row)
        self._audit("ApprovalRequested", request_id, PENDING, created)
        return self.load(request_id)

    def load(self, request_id: str) -> ApprovalRequest:
        validate_id(request_id)
        rows = self._db.query("SELECT * FROM approvals WHERE id = ?", (request_id,))
        if not rows:
            raise _err(ErrorCode.TASK_NOT_FOUND, "Approval request not found.")
        return _from_row(rows[0])

    def pending(self, task_id: str) -> list[ApprovalRequest]:
        rows = self._db.query(
            "SELECT * FROM approvals WHERE task_id = ? AND status = ? ORDER BY created_at, id",
            (task_id, PENDING),
        )
        return [_from_row(r) for r in rows]

    def decide(self, request_id: str, *, approve: bool, at: str | None = None) -> ApprovalRequest:
        current = self.load(request_id)
        when = at or now_utc()
        validate_timestamp(when)
        if current.status != PENDING:
            raise _err(
                ErrorCode.TASK_INVALID,
                f"Approval is {current.status}; only a PENDING request can be decided.",
                task_id=current.task_id,
            )
        if when >= current.expires_at:
            self._set_status(request_id, EXPIRED, when, from_status=PENDING)
            self._audit("ApprovalExpired", request_id, EXPIRED, when)
            raise _err(ErrorCode.TASK_INVALID, "Approval expired before it was decided.", task_id=current.task_id)
        new_status = APPROVED if approve else DENIED
        self._set_status(request_id, new_status, when, from_status=PENDING)
        self._audit(f"Approval{'Granted' if approve else 'Denied'}", request_id, new_status, when)
        return self.load(request_id)

    def consume(
        self,
        request_id: str,
        *,
        tool_id: str,
        arguments: dict[str, Any],
        task_id: str,
        step_id: str,
        at: str | None = None,
        authority_digest: str = "",
    ) -> ApprovalRequest:
        """Spend an APPROVED request for exactly this operation. Raises if it cannot authorise it."""
        current = self.load(request_id)
        when = at or now_utc()
        validate_timestamp(when)
        if current.status != APPROVED:
            raise _err(
                ErrorCode.TASK_INVALID,
                f"Approval is {current.status}; the call is not authorised.",
                task_id=task_id,
            )
        if when >= current.expires_at:
            self._set_status(request_id, EXPIRED, when, from_status=APPROVED)
            self._audit("ApprovalExpired", request_id, EXPIRED, when)
            raise _err(ErrorCode.TASK_INVALID, "Approval expired; the call is not authorised.", task_id=task_id)
        expected = fingerprint(tool_id=tool_id, arguments=arguments, task_id=task_id, step_id=step_id, authority_digest=authority_digest)
        if expected != current.fingerprint:
            raise _err(
                ErrorCode.TASK_INVALID,
                "Approval does not match this operation; the call is not authorised.",
                task_id=task_id,
            )
        self._set_status(request_id, CONSUMED, when, from_status=APPROVED, consumed=True)
        self._audit("ApprovalConsumed", request_id, CONSUMED, when)
        return self.load(request_id)

    def _set_status(
        self, request_id: str, status: str, at: str, *, from_status: str, consumed: bool = False
    ) -> None:
        with self._db.transaction() as conn:
            if consumed:
                cursor = conn.execute(
                    "UPDATE approvals SET status = ?, consumed_at = ? WHERE id = ? AND status = ?",
                    (status, at, request_id, from_status),
                )
            else:
                cursor = conn.execute(
                    "UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = ?",
                    (status, at, request_id, from_status),
                )
            if cursor.rowcount != 1:
                raise _err(ErrorCode.TASK_REVISION_CONFLICT, "Approval was changed concurrently; reload and retry.")

    def _audit(self, event_type: str, request_id: str, status: str, at: str) -> None:
        row = self._db.query_one("SELECT task_id FROM approvals WHERE id = ?", (request_id,))
        self._db.insert_row(
            "events",
            {
                "id": generate_id("event"),
                "timestamp": at,
                "type": event_type,
                "component": COMPONENT,
                "task_id": row["task_id"] if row else "",
                "session_id": "",
                "payload_json": json.dumps({"approval_id": request_id, "status": status}),
            },
        )


def _from_row(row: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        id=row["id"],
        task_id=row["task_id"],
        step_id=row["step_id"],
        tool_id=row["tool_id"],
        fingerprint=row["fingerprint"],
        explanation=row["explanation"],
        preview=json.loads(row["preview_json"]),
        resource=row["resource"],
        risk=row["risk"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        decided_at=row["decided_at"],
        consumed_at=row["consumed_at"],
    )
