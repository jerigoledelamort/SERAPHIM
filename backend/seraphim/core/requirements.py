"""Shared deterministic requirements resolver used by observation and commit."""
import json

from seraphim.core.evidence import CheckSpec
from seraphim.core.task_model import TASK_SCOPE, StepStatus


class Requirements:
    def __init__(self, root):
        self.root = root

    def resolve(self, task, target, rows):
        final = target == TASK_SCOPE
        checks = []
        for step in task.steps if final else (task.step(target),):
            checks.extend(self._plan_checks(step, final))
            if final and step.status is StepStatus.SUCCEEDED:
                checks.append(CheckSpec("accepted_step", step.id))
        mutable = {}
        for row in rows:
            if (not final and row["step_id"] != target) or not row["result_json"]:
                continue
            self._call_checks(row, checks, mutable)
        return list(dict.fromkeys([*checks, *mutable.values()]))

    def _plan_checks(self, step, final=False) -> list[CheckSpec]:
        checks = []
        for criterion in step.verification:
            # Structured criteria are JSON strings, preserving legacy tuple[str] plans.
            if criterion.startswith("{"):
                try:
                    data = json.loads(criterion)
                    scope = data.pop("scope", "step")
                    if scope not in ("step", "final"):
                        raise ValueError("Invalid criterion scope")
                    if final and scope != "final":
                        continue
                    checks.append(CheckSpec(**data))
                except (TypeError, ValueError):
                    checks.append(CheckSpec("unsupported", criterion))
            elif final:
                continue
            elif criterion in ("file_exists", "file_hash", "file_content"):
                checks.extend(CheckSpec(criterion, target) for target in step.expected_outputs)
                if not step.expected_outputs:
                    checks.append(CheckSpec("unsupported", criterion))
            else:
                checks.append(CheckSpec(criterion))
        return checks

    def _call_checks(self, row, checks, mutable) -> None:
        call = json.loads(row["call_json"])
        manifest = json.loads(row["manifest_json"]) if row.get("manifest_json") else None
        checks.append(CheckSpec("tool_result", call_id=row["call_id"]))
        path = call["arguments"].get("path", "")
        key = self.root.identity(path) if path else ""
        if call["tool_id"] == "tool.fs.write_file":
            mutable[key] = CheckSpec("file_content", path, call["arguments"]["text"], call_id=row["call_id"])
        if call["tool_id"] == "tool.fs.create_dir":
            mutable[key] = CheckSpec("file_exists", path, call_id=row["call_id"])
        if call["tool_id"] == "tool.fs.delete_file":
            mutable[key] = CheckSpec("file_absent", path, call_id=row["call_id"])
        if call["tool_id"] == "tool.fs.move_path":
            destination = call["arguments"]["to"]
            previous = mutable.get(key)
            mutable[self.root.identity(destination)] = CheckSpec(
                previous.kind if previous and previous.kind == "file_content" else "file_exists",
                destination, previous.expected if previous and previous.kind == "file_content" else "",
                call_id=row["call_id"])
            mutable[key] = CheckSpec("file_absent", path, call_id=row["call_id"])
        if call["tool_id"] == "tool.process.run":
            checks.append(CheckSpec("command_exit", expected="0", call_id=row["call_id"]))
        if manifest is None:
            checks.append(CheckSpec("manifest.unavailable", call_id=row["call_id"]))
        for kind in (manifest or {}).get("verification", ()):
            checks.append(CheckSpec(kind, call["arguments"].get("path", ""), call_id=row["call_id"]))
