from __future__ import annotations

import json
from dataclasses import asdict
from functools import wraps
from pathlib import Path

import click

from seraphim.core import authority
from seraphim.core.approval import ApprovalService
from seraphim.core.offline_runtime import OfflineRuntime
from seraphim.core.recovery import RecoveryEngine
from seraphim.core.task_service import TaskService


def _json_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except click.exceptions.Exit:
            raise
        except Exception as exc:
            _emit({"error": {"type": type(exc).__name__, "code": str(getattr(exc, "code", "TASK_INVALID"))}})
            raise click.exceptions.Exit(1) from exc
    return wrapped


def _emit(value) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))


@click.group(name="task")
@click.option("--root", required=True, type=click.Path(path_type=Path))
@click.option("--sandbox", required=True, type=click.Path(path_type=Path))
@click.option("--script", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--policy", type=click.Choice(["allow", "deny", "ask"]), default="allow")
@click.pass_context
def task_group(ctx, root, sandbox, script, policy):
    """Offline FakeProvider tasks. All output is JSON; no live providers."""
    try:
        ctx.obj = OfflineRuntime(root, sandbox, script, policy)
    except Exception as exc:
        _emit({"error": {"type": type(exc).__name__, "code": "RUNTIME_INVALID"}})
        raise click.exceptions.Exit(1) from exc


@task_group.command("create")
@click.argument("goal")
@click.pass_obj
@_json_errors
def create(runtime, goal):
    _emit({"task_id": runtime.executor.create(goal)})


@task_group.command("run")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def run(runtime, task_id):
    runtime.run(task_id)
    record = runtime.executor.tasks.load(task_id)
    _emit(asdict(record))
    if record.task.status.value != "SUCCEEDED":
        raise click.exceptions.Exit(1)


@task_group.command("list")
@click.pass_obj
@_json_errors
def list_tasks(runtime):
    _emit([asdict(record) for record in runtime.executor.tasks.list_tasks()])


@task_group.command("show")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def show(runtime, task_id):
    _emit(asdict(runtime.executor.tasks.load(task_id)))


@task_group.command("events")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def events(runtime, task_id):
    _emit(runtime.db.query("SELECT * FROM events WHERE task_id=? ORDER BY rowid", (task_id,)))


@task_group.command("report")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def report(runtime, task_id):
    _emit({"runs": runtime.db.query("SELECT * FROM verification_runs WHERE task_id=? ORDER BY rowid", (task_id,)),
           "evidence": runtime.db.query("SELECT * FROM verification_evidence WHERE task_id=? ORDER BY rowid", (task_id,))})


@task_group.command("inspect")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def inspect(runtime, task_id):
    _emit(RecoveryEngine(runtime.db).inspect(task_id))


@task_group.command("pause")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def pause(runtime, task_id):
    _emit(asdict(TaskService(runtime.db).pause(task_id)))


@task_group.command("resume")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def resume(runtime, task_id):
    authority.validate(runtime.db, task_id, runtime.executor.registry)
    TaskService(runtime.db).resume(task_id)
    runtime.run(task_id)
    _emit(asdict(runtime.executor.tasks.load(task_id)))


@task_group.command("cancel")
@click.argument("task_id")
@click.pass_obj
@_json_errors
def cancel(runtime, task_id):
    runtime.executor.orchestrator.cancel(task_id, "Cancelled through offline CLI")
    _emit(asdict(runtime.executor.tasks.load(task_id)))


@task_group.command("approve")
@click.argument("task_id")
@click.argument("approval_id")
@click.pass_obj
@_json_errors
def approve(runtime, task_id, approval_id):
    runtime.executor.approve(task_id, approval_id)
    runtime.run(task_id)
    _emit(asdict(runtime.executor.tasks.load(task_id)))


@task_group.command("deny")
@click.argument("task_id")
@click.argument("approval_id")
@click.pass_obj
@_json_errors
def deny(runtime, task_id, approval_id):
    approval = ApprovalService(runtime.db).load(approval_id)
    runtime.executor.orchestrator.deny(task_id, approval.step_id, approval_id)
    _emit(asdict(runtime.executor.tasks.load(task_id)))
