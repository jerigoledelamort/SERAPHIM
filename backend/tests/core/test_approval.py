# CORE approval service tests (S23). Offline; real SQLite in a temp root.
from __future__ import annotations

from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.core.approval import (
    APPROVED,
    CONSUMED,
    DENIED,
    EXPIRED,
    PENDING,
    ApprovalService,
    fingerprint,
    preview,
)
from seraphim.core.task_model import PlanStep, TaskMode, create_task
from seraphim.core.task_store import TaskRepository
from seraphim.storage import Database, MigrationRunner

TS = "2026-11-12T10:00:00.000Z"
LATER = "2026-11-12T10:01:00.000Z"
AFTER_EXPIRY = "2026-11-12T10:10:00.000Z"
TOOL = "tool.fs.delete_file"


def _db(root: Path) -> Database:
    db = Database.open(root, environ={})
    MigrationRunner(db).run()
    return db


@pytest.fixture
def db(test_root: Path) -> Database:
    return _db(test_root)


@pytest.fixture
def task_ids(db: Database) -> tuple[str, str]:
    step = generate_id("step")
    draft = create_task(
        "goal",
        TaskMode.EXECUTE_WITH_APPROVAL,
        (PlanStep(id=step, title="s", verification=("file_exists",), risk_hint="destructive"),),
        at=TS,
    )
    repo = TaskRepository(db)
    repo.insert(draft)
    return draft.id, step


def _service(db: Database) -> ApprovalService:
    return ApprovalService(db)


def _request(service: ApprovalService, task_id: str, step_id: str, args: dict, **kw):
    return service.request(
        task_id=task_id,
        step_id=step_id,
        tool_id=TOOL,
        arguments=args,
        explanation="Delete one file",
        resource="notes/a.txt",
        risk="high",
        at=TS,
        **kw,
    )


def test_request_is_pending_and_never_authorises(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "notes/a.txt"})
    assert req.status == PENDING
    assert req.decided_at == ""
    with pytest.raises(SeraphimError):
        service.consume(
            req.id, tool_id=TOOL, arguments={"path": "notes/a.txt"},
            task_id=task_ids[0], step_id=task_ids[1], at=LATER,
        )


def test_preview_is_redacted_and_bounded(db, task_ids):
    service = _service(db)
    secret = "sk-" + "a" * 40
    req = _request(service, *task_ids, {"path": "x" * 900, "note": f"key={secret}"})
    assert len(req.preview["path"]) <= 501
    assert secret not in req.preview["note"]
    assert secret not in str(db.query("SELECT preview_json FROM approvals"))


def test_granted_approval_is_consumed_once(db, task_ids):
    service = _service(db)
    args = {"path": "notes/a.txt"}
    req = _request(service, *task_ids, args)
    service.decide(req.id, approve=True, at=LATER)
    done = service.consume(req.id, tool_id=TOOL, arguments=args, task_id=task_ids[0], step_id=task_ids[1], at=LATER)
    assert done.status == CONSUMED
    with pytest.raises(SeraphimError):
        service.consume(req.id, tool_id=TOOL, arguments=args, task_id=task_ids[0], step_id=task_ids[1], at=LATER)


def test_duplicate_decision_is_rejected(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "a"})
    service.decide(req.id, approve=True, at=LATER)
    with pytest.raises(SeraphimError) as exc:
        service.decide(req.id, approve=False, at=LATER)
    assert exc.value.code == ErrorCode.TASK_INVALID
    assert service.load(req.id).status == APPROVED


def test_denied_request_cannot_be_approved_later(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "a"})
    service.decide(req.id, approve=False, at=LATER)
    with pytest.raises(SeraphimError):
        service.decide(req.id, approve=True, at=LATER)
    assert service.load(req.id).status == DENIED


def test_approval_cannot_be_reused_for_different_arguments(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "notes/a.txt"})
    service.decide(req.id, approve=True, at=LATER)
    with pytest.raises(SeraphimError):
        service.consume(
            req.id, tool_id=TOOL, arguments={"path": "notes/other.txt"},
            task_id=task_ids[0], step_id=task_ids[1], at=LATER,
        )
    assert service.load(req.id).status == APPROVED


def test_approval_cannot_be_reused_for_other_tool_task_or_step(db, task_ids):
    service = _service(db)
    args = {"path": "a"}
    req = _request(service, *task_ids, args)
    service.decide(req.id, approve=True, at=LATER)
    for kwargs in (
        {"tool_id": "tool.fs.move_path", "task_id": task_ids[0], "step_id": task_ids[1]},
        {"tool_id": TOOL, "task_id": generate_id("task"), "step_id": task_ids[1]},
        {"tool_id": TOOL, "task_id": task_ids[0], "step_id": generate_id("step")},
    ):
        with pytest.raises(SeraphimError):
            service.consume(req.id, arguments=args, at=LATER, **kwargs)
    assert service.load(req.id).status == APPROVED


def test_expired_pending_request_cannot_be_decided(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "a"}, ttl_seconds=60)
    with pytest.raises(SeraphimError):
        service.decide(req.id, approve=True, at=AFTER_EXPIRY)
    assert service.load(req.id).status == EXPIRED


def test_expired_approval_cannot_be_consumed(db, task_ids):
    service = _service(db)
    args = {"path": "a"}
    req = _request(service, *task_ids, args, ttl_seconds=60)
    service.decide(req.id, approve=True, at="2026-11-12T10:00:30.000Z")
    with pytest.raises(SeraphimError):
        service.consume(req.id, tool_id=TOOL, arguments=args, task_id=task_ids[0], step_id=task_ids[1], at=AFTER_EXPIRY)
    assert service.load(req.id).status == EXPIRED


@pytest.mark.parametrize("ttl", [0, 9, 3601, True, "60"])
def test_ttl_bounds_are_enforced(db, task_ids, ttl):
    with pytest.raises(SeraphimError):
        _request(_service(db), *task_ids, {"path": "a"}, ttl_seconds=ttl)


def test_empty_explanation_is_rejected(db, task_ids):
    with pytest.raises(SeraphimError):
        _service(db).request(
            task_id=task_ids[0], step_id=task_ids[1], tool_id=TOOL, arguments={},
            explanation="", resource="", risk="high", at=TS,
        )


def test_audit_events_record_each_decision(db, task_ids):
    service = _service(db)
    req = _request(service, *task_ids, {"path": "a"})
    service.decide(req.id, approve=True, at=LATER)
    types = [r["type"] for r in db.query("SELECT type FROM events WHERE payload_json LIKE ? ORDER BY rowid", (f"%{req.id}%",))]
    assert types == ["ApprovalRequested", "ApprovalGranted"]


def test_fingerprint_is_stable_and_order_independent():
    a = fingerprint(tool_id=TOOL, arguments={"x": 1, "y": 2}, task_id="t", step_id="s")
    b = fingerprint(tool_id=TOOL, arguments={"y": 2, "x": 1}, task_id="t", step_id="s")
    assert a == b
    assert len(a) == 64


def test_preview_limits_length_without_leaking_raw_dict():
    view = preview({"path": "p" * 600})
    assert view["path"].endswith("…")
    assert set(view) == {"path"}
