import pytest
from seraphim.contracts.errors import SeraphimError
from seraphim.contracts.timestamps import now_utc
from seraphim.core.evidence import CheckSpec
from seraphim.core.task_machine import Verified
from seraphim.core.verification import VerificationEngine
from seraphim.model_layer.fake import FakeTurn
from seraphim.wings.fs_paths import FsRoot

from tests.core.test_executor import _call, _runtime
from tests.core.test_verification import _executed


def test_persisted_diagnostic_subset_cannot_authorize(tmp_path):
    executor, engine, task_id, root, db = _executed(tmp_path)
    (root / 'a.txt').write_text('wrong')
    record = executor.tasks.load(task_id)
    report = engine.check(task_id, record.task.pending_verification, [CheckSpec('file_exists', 'a.txt')])
    db.execute('DELETE FROM execution_state WHERE task_id=?', (task_id,))
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(record.task.pending_verification, report), event_type='Verified', at=now_utc())


def test_equivalent_path_composes(tmp_path):
    executor, _, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call(), _call(arguments={'path': './a.txt', 'text': 'two'}, call_id='second')]), FakeTurn(text='done')])
    task_id = executor.create('write')
    executor.run(task_id)
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    assert engine.verify_pending(task_id).passed
    assert engine.finish_task(task_id).passed


@pytest.mark.parametrize('change', ['root', 'manifest', 'schema', 'contract'])
def test_approval_authority_change_before_accounting(tmp_path, change):
    from dataclasses import replace

    from seraphim.aegis import PolicySet
    from seraphim.core.approval import ApprovalService
    from seraphim.wings.fs_tools import register_fs_tools
    from seraphim.wings.registry import ToolRegistry
    executor, _, root, db = _runtime(tmp_path, [FakeTurn(tool_calls=[_call()]), FakeTurn(text='done')])
    from seraphim.aegis import PolicyEngine, PolicyRule
    executor.orchestrator._engine = PolicyEngine(PolicySet((
        PolicyRule(rule_id='aegis.global.confirm', source='global', outcome='ASK_USER', waived_when_confirmed=True),
        PolicyRule(rule_id='aegis.user.allow', source='user', outcome='ALLOW'),
    )))
    task_id = executor.create('write')
    assert executor.run(task_id).status == 'NEEDS_APPROVAL'
    approval = ApprovalService(db).pending(task_id)[0]
    if change == 'root':
        other = tmp_path / 'other'
        other.mkdir()
        registry = ToolRegistry()
        register_fs_tools(registry, FsRoot(other))
        executor.registry = registry
        executor.orchestrator._registry = registry
    else:
        entry = executor.registry._entries['tool.fs.write_file']
        if change == 'manifest':
            entry.manifest = replace(entry.manifest, version='2.0')
        elif change == 'schema':
            entry.manifest = replace(entry.manifest, input_schema={'type': 'object'})
        else:
            entry.manifest = replace(entry.manifest, verification=('app_state',))
    before = executor.store.get_state(task_id)
    with pytest.raises(SeraphimError):
        executor.approve(task_id, approval.id)
    assert executor.store.get_state(task_id) == before
    assert not ApprovalService(db).load(approval.id).consumed_at
    assert not (root / 'a.txt').exists()


@pytest.mark.parametrize('final', [False, True])
def test_intermediate_content_and_explicit_final(tmp_path, final):
    import json
    from dataclasses import replace

    from seraphim.core.task_model import TaskStatus
    from seraphim.model_layer.fake import FakeProvider
    executor, provider, root, db = _runtime(tmp_path, [])
    criterion = {'kind': 'file_content', 'target': 'a.txt', 'expected': 'one'}
    if final:
        criterion['scope'] = 'final'
    plan = {'goal': 'two writes', 'steps': [
        {'id': 'one', 'title': 'first', 'verification': [json.dumps(criterion)]},
        {'id': 'two', 'title': 'second', 'depends_on': ['one'], 'verification': [json.dumps({'kind': 'file_content', 'target': 'a.txt', 'expected': 'two'})]}]}
    replacement = FakeProvider(capabilities=provider.capabilities(), script=[FakeTurn(text=json.dumps(plan)),
        FakeTurn(tool_calls=[_call(arguments={'path': 'a.txt', 'text': 'one'})]), FakeTurn(text='done'),
        FakeTurn(tool_calls=[_call(arguments={'path': './a.txt', 'text': 'two'})]), FakeTurn(text='done')])
    executor.candidates = {key: replace(candidate, provider=replacement) for key, candidate in executor.candidates.items()}
    task_id = executor.create('two writes')
    engine = VerificationEngine(db, executor.registry, FsRoot(root))
    executor.run(task_id)
    assert engine.verify_pending(task_id).passed
    executor.run(task_id)
    assert engine.verify_pending(task_id).passed
    assert engine.finish_task(task_id).passed is (not final)
    assert executor.tasks.load(task_id).task.status is (TaskStatus.FAILED if final else TaskStatus.SUCCEEDED)


@pytest.mark.parametrize("change", ["revision", "history", "expected", "mandatory", "call_id", "outcome", "evidence", "target", "reuse", "cancel", "open_ledger"])
def test_authoritative_run_binding_rejects_tampering(tmp_path, change):
    import json
    from dataclasses import replace

    from seraphim.core import authority
    executor, engine, task_id, _root, db = _executed(tmp_path)
    record = executor.tasks.load(task_id)
    target = record.task.pending_verification
    checks = engine.requirements(task_id, target)
    context = authority.validate(db, task_id, engine.registry)
    with db.transaction() as conn:
        history = authority.history(conn, task_id)
    report = engine._check(task_id, target, checks, (record.revision, context, history))
    if change == "revision":
        db.execute("UPDATE verification_authorizations SET revision=revision-1 WHERE task_id=?", (task_id,))
    elif change == "history":
        db.execute("UPDATE execution_dispatches SET result_json=? WHERE task_id=?", ('{}', task_id))
    elif change in ("expected", "mandatory", "call_id", "evidence"):
        evidence = db.query_one("SELECT * FROM verification_evidence WHERE id=?", (report.checks[0].evidence_ref,))
        data = json.loads(evidence["payload_json"])
        if change == "evidence":
            data["observation"]["passed"] = False
        else:
            data["check"][change] = False if change == "mandatory" else "altered"
        db.execute("UPDATE verification_evidence SET payload_json=? WHERE id=?", (json.dumps(data), evidence["id"]))
    elif change == "outcome":
        report = replace(report, checks=(replace(report.checks[0], mandatory=False), *report.checks[1:]))
    elif change == "target":
        target = "other"
    elif change == "reuse":
        db.execute("UPDATE verification_authorizations SET consumed=1 WHERE task_id=?", (task_id,))
    elif change == "open_ledger":
        db.execute("INSERT INTO tool_calls(id,task_id,step_id,operation,idempotency_key,status,started_at) VALUES(?,?,?,?,?,?,?)", ("dangling", task_id, target, "tool.fs.write_file", "dangling", "UNKNOWN", now_utc()))
    elif change == "cancel":
        db.execute("UPDATE execution_state SET cancel_requested=1 WHERE task_id=?", (task_id,))
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(target, report), event_type="Verified", at=now_utc())
    assert executor.tasks.load(task_id).revision == record.revision


def test_two_authoritative_runs_only_one_can_transition(tmp_path):
    from seraphim.core import authority
    executor, engine, task_id, _root, db = _executed(tmp_path)
    record = executor.tasks.load(task_id)
    target = record.task.pending_verification
    with db.transaction() as conn:
        history = authority.history(conn, task_id)
    binding = (record.revision, authority.validate(db, task_id, engine.registry), history)
    reports = [engine._check(task_id, target, engine.requirements(task_id, target), binding) for _ in range(2)]
    executor.tasks.save(record, Verified(target, reports[0]), event_type="Verified", at=now_utc())
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(target, reports[1]), event_type="Verified", at=now_utc())
    assert db.query_one("SELECT SUM(consumed) AS n FROM verification_authorizations WHERE task_id=?", (task_id,))["n"] == 1


@pytest.mark.parametrize("checks", [[], [CheckSpec("file_exists", "a.txt", mandatory=False)]])
def test_diagnostic_empty_or_optional_cannot_authorize(tmp_path, checks):
    executor, engine, task_id, _root, _db = _executed(tmp_path)
    record = executor.tasks.load(task_id)
    report = engine.check(task_id, record.task.pending_verification, checks)
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(record.task.pending_verification, report), event_type="Verified", at=now_utc())


def test_complete_diagnostic_report_still_cannot_authorize(tmp_path):
    executor, engine, task_id, _root, _db = _executed(tmp_path)
    record = executor.tasks.load(task_id)
    target = record.task.pending_verification
    report = engine.check(task_id, target, engine.requirements(task_id, target))
    assert report.passed
    with pytest.raises(SeraphimError):
        executor.tasks.save(record, Verified(target, report), event_type="Verified", at=now_utc())
    assert executor.tasks.load(task_id).revision == record.revision


def test_registry_provider_swap_during_policy_does_not_change_invocation(tmp_path):
    from types import SimpleNamespace

    from seraphim.contracts.ids import generate_id
    from seraphim.wings.calls import ToolCall

    executor, _provider, root, _db = _runtime(tmp_path, [])
    registry = executor.registry
    entry = registry._entries["tool.fs.write_file"]

    class Replacement:
        invoked = False

        def invoke(self, manifest, arguments):
            self.invoked = True
            raise AssertionError("Replacement provider must not be invoked")

    replacement = Replacement()

    def policy(manifest, call):
        entry.provider = replacement
        return SimpleNamespace(allowed=True, limits=None)

    result = registry.call(ToolCall(generate_id("call"), "tool.fs.write_file", {"path": "a.txt", "text": "hello"}), policy=policy)
    assert result.status.value == "SUCCEEDED"
    assert not replacement.invoked
    assert (root / "a.txt").read_bytes() == b"hello"


def test_observer_root_must_match_authority(tmp_path):
    executor, _, task_id, _root, db = _executed(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.txt").write_text("hello")
    engine = VerificationEngine(db, executor.registry, FsRoot(other))
    with pytest.raises(SeraphimError):
        engine.verify_pending(task_id)
