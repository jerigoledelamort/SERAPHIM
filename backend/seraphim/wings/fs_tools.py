# WINGS filesystem tools (S21): manifests and the provider that runs them inside one root.
# The provider is reached only through ToolRegistry.call(), which asks AEGIS first.

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.wings import fs_ops
from seraphim.wings.fs_paths import COMPONENT, FsRoot
from seraphim.wings.manifest import ToolManifest

_OUTPUT_OBJECT = {"type": "object"}


def _path_schema(extra: dict[str, Any] | None = None, required: tuple[str, ...] = ("path",)) -> dict[str, Any]:
    properties: dict[str, Any] = {"path": {"type": "string"}}
    properties.update(extra or {})
    return {"type": "object", "properties": properties, "required": list(required)}


def _manifest(
    tool_id: str,
    description: str,
    input_schema: dict[str, Any],
    side_effects: str,
    risk: str,
    permission: str,
) -> ToolManifest:
    return ToolManifest(
        id=tool_id,
        description=description,
        input_schema=input_schema,
        output_schema=_OUTPUT_OBJECT,
        capabilities=(permission,),
        risk=risk,
        side_effects=side_effects,
        permissions=(permission,),
        timeout_seconds=10,
        supports_cancellation=False,
        idempotency="idempotent" if side_effects == "read" else "non_idempotent",
        source="core",
        version="1.0",
    )


TOOL_MANIFESTS: tuple[ToolManifest, ...] = (
    _manifest("tool.fs.read_file", "Read a UTF-8 text file inside the root.", _path_schema(), "read", "low", "filesystem.read"),
    _manifest("tool.fs.list_dir", "List a directory inside the root.", _path_schema(), "read", "low", "filesystem.read"),
    _manifest(
        "tool.fs.search_text",
        "Search UTF-8 text files under a directory inside the root.",
        _path_schema({"query": {"type": "string"}}, required=("path", "query")),
        "read",
        "low",
        "filesystem.read",
    ),
    _manifest(
        "tool.fs.write_file",
        "Atomically write a UTF-8 text file inside the root.",
        _path_schema({"text": {"type": "string"}}, required=("path", "text")),
        "write",
        "medium",
        "filesystem.write",
    ),
    _manifest("tool.fs.create_dir", "Create a directory inside the root.", _path_schema(), "write", "low", "filesystem.write"),
    _manifest(
        "tool.fs.move_path",
        "Move a file or directory inside the root.",
        _path_schema({"to": {"type": "string"}}, required=("path", "to")),
        "write",
        "medium",
        "filesystem.write",
    ),
    _manifest(
        "tool.fs.delete_file",
        "Move a file into the root's _trash backup folder (recoverable).",
        _path_schema(),
        "destructive",
        "high",
        "filesystem.delete",
    ),
)


class FsToolProvider:
    def __init__(self, root: FsRoot) -> None:
        self._root = root
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "tool.fs.read_file": lambda a: fs_ops.read_file(self._root, a["path"]),
            "tool.fs.list_dir": lambda a: fs_ops.list_dir(self._root, a["path"]),
            "tool.fs.search_text": lambda a: fs_ops.search_text(self._root, a["path"], a["query"]),
            "tool.fs.write_file": lambda a: fs_ops.write_file(self._root, a["path"], a["text"]),
            "tool.fs.create_dir": lambda a: fs_ops.create_dir(self._root, a["path"]),
            "tool.fs.move_path": lambda a: fs_ops.move_path(self._root, a["path"], a["to"]),
            "tool.fs.delete_file": lambda a: fs_ops.delete_path(self._root, a["path"]),
        }

    def policy_resources(self, manifest: ToolManifest, arguments: dict[str, Any]) -> tuple[str, ...]:
        names = ("path", "to") if manifest.id == "tool.fs.move_path" else ("path",)
        return tuple(str(self._root.resolve(arguments[name], must_exist=False)) for name in names)

    def invoke(self, manifest: ToolManifest, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(manifest.id)
        if handler is None:
            raise SeraphimError(code=ErrorCode.TOOL_NOT_FOUND, component=COMPONENT, safe_message="Unknown filesystem tool.")
        return handler(arguments)


def register_fs_tools(registry: Any, root: FsRoot) -> None:
    provider = FsToolProvider(root)
    for manifest in TOOL_MANIFESTS:
        registry.register(manifest, provider)
