"""Versioned, canonical runtime authority. No legacy context is inferred."""
import hashlib
import json
import os

from seraphim.contracts.errors import ErrorCode, SeraphimError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def snapshot(registry):
    entries = []
    for tool_id, entry in sorted(registry._entries.items()):
        root = getattr(entry.provider, "_root", getattr(entry.provider, "_sandbox", None))
        entries.append({"tool": tool_id, "manifest": entry.manifest.to_dict(), "enabled": entry.enabled,
                        "root": os.path.normcase(str(root.path)) if root else None,
                        "allowed_executables": sorted(getattr(entry.provider, "_allowed", ())),
                        "provider": type(entry.provider).__module__ + "." + type(entry.provider).__qualname__})
    return canonical({"version": 1, "entries": entries})


def invalid():
    return SeraphimError(code=ErrorCode.TASK_INVALID, component="core.authority",
                         safe_message="Runtime authority changed or is unavailable; operator review required.")


def bind(db, task_id, registry):
    raw = snapshot(registry)
    with db.transaction() as conn:
        row = conn.execute("SELECT authority_json,managed_verification FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row["authority_json"] and row["authority_json"] != raw:
            raise invalid()
        if not row["authority_json"] and row["managed_verification"]:
            raise invalid()
        conn.execute("UPDATE tasks SET authority_json=?,managed_verification=1 WHERE id=?", (raw, task_id))
    return raw


def validate(db, task_id, registry):
    row = db.query_one("SELECT authority_json FROM tasks WHERE id=?", (task_id,))
    if not row or not row["authority_json"] or row["authority_json"] != snapshot(registry):
        raise invalid()
    return row["authority_json"]


def operation(registry, call, sensitivity):
    manifest = registry.manifest(call.tool_id)
    return canonical({"version": 1, "context": snapshot(registry), "manifest": manifest.to_dict(),
                      "resources": [os.path.normcase(p) for p in registry.policy_resources(manifest, call)],
                      "sensitivity": sensitivity})


def history(conn, task_id):
    rows = conn.execute("SELECT d.*,l.status AS ledger_status FROM execution_dispatches d LEFT JOIN tool_calls l ON l.id=d.ledger_call_id WHERE d.task_id=? ORDER BY d.rowid", (task_id,)).fetchall()
    return canonical([dict(r) for r in rows])
