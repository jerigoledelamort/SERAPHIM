from __future__ import annotations

import os
import subprocess
import sys

import pytest
from seraphim.contracts.timestamps import now_utc
from seraphim.core.recovery import RecoveryEngine
from seraphim.core.task_machine import StartStep
from seraphim.model_layer.fake import FakeTurn

from tests.core.test_executor import _runtime


@pytest.mark.parametrize("window", ["before_intent", "after_intent", "after_effect"])
def test_subprocess_crash_never_replays_unknown_write(tmp_path, window):
    executor, _provider, root, db = _runtime(tmp_path, [FakeTurn(text="unused")])
    task_id = executor.create("crash window")
    step_id = executor.tasks.load(task_id).task.steps[0].id
    executor.tasks.save(executor.tasks.load(task_id), StartStep(step_id), event_type="StepStarted", at=now_utc())
    script = """
import os, sys
from pathlib import Path
from seraphim.storage.db import Database
from seraphim.core.dispatch_store import DispatchStore
from seraphim.wings.calls import ToolCall
from seraphim.contracts.ids import generate_id
path, task_id, step_id, marker, window = sys.argv[1:]
store = DispatchStore(Database(path=Path(path)))
if window == 'before_intent':
    os._exit(17)
call = ToolCall(generate_id('call'), 'tool.fs.write_file', {'path':'a.txt','text':'once'}, task_id, step_id)
store.claim(task_id, 'crashed-child')
store.reserve(task_id, step_id, call, 'internal', owner='crashed-child')
store.begin(call.call_id, owner='crashed-child')
if window == 'after_effect':
    Path(marker).write_text('once')
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-c", script, str(db.path), task_id, step_id,
                             str(root / "a.txt"), window], env={**os.environ, "PYTHONPATH": "backend"},
                            capture_output=True, timeout=20)
    assert result.returncode == 17, result.stderr.decode()
    checkpoint = RecoveryEngine(db).inspect(task_id)
    if window == "before_intent":
        assert not checkpoint["calls"]
        assert not (root / "a.txt").exists()
    else:
        assert checkpoint["decision"] == "owned_inspection_only"
        from seraphim.contracts.errors import SeraphimError

        with pytest.raises(SeraphimError):
            executor.run(task_id)
        assert len(executor.store.calls(task_id)) == 1
        assert (root / "a.txt").exists() == (window == "after_effect")
        if window == "after_effect":
            assert (root / "a.txt").read_text() == "once"
