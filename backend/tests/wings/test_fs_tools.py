# WINGS filesystem tools (S21). Real temp directories; junctions are created with mklink /J
# (no admin needed on Windows). Symlinks are skipped where the OS refuses them.

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from seraphim.aegis import PolicyEngine, PolicyRule, build_policy_set, make_gate
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.ids import generate_id
from seraphim.wings import CallStatus, ToolCall, ToolRegistry, fs_ops
from seraphim.wings.fs_paths import FsRoot
from seraphim.wings.fs_tools import register_fs_tools


def _gate(*, destructive: bool = False) -> Any:
    rules = [
        PolicyRule(
            rule_id="aegis.user.fs_read_write",
            outcome="ALLOW",
            source="user",
            tool_pattern="tool.fs.*",
            side_effects=("read", "write"),
        )
    ]
    if destructive:
        rules.append(
            PolicyRule(
                rule_id="aegis.user.fs_destructive",
                outcome="ALLOW",
                source="user",
                tool_pattern="tool.fs.delete_file",
                side_effects=("destructive",),
            )
        )
    return make_gate(PolicyEngine(build_policy_set(tuple(rules))), actor="test")


@pytest.fixture
def sandbox(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret_outside.txt").write_text("OUTSIDE", encoding="utf-8")
    (root / "notes.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
    return {"root": root, "outside": outside}


@pytest.fixture
def fs_root(sandbox: dict[str, Path]) -> FsRoot:
    return FsRoot(sandbox["root"])


def _registry(fs_root: FsRoot) -> ToolRegistry:
    registry = ToolRegistry()
    register_fs_tools(registry, fs_root)
    return registry


def _call(registry: ToolRegistry, tool_id: str, gate: Any | None = None, **arguments: Any) -> Any:
    return registry.call(
        ToolCall(call_id=generate_id("call"), tool_id=tool_id, arguments=arguments),
        policy=gate if gate is not None else _gate(),
    )


def _make_junction(link: Path, target: Path) -> None:
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if result.returncode != 0 or not link.exists():
        pytest.skip("junction creation not available")


def _make_symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation requires privilege on this host")


class TestTraversalAndAbsolute:
    @pytest.mark.parametrize(
        "relative",
        ["../outside/secret_outside.txt", "a/../../outside/secret_outside.txt", "..", "/etc/passwd", "C:/x.txt", "C:x.txt", "\\\\server\\share\\x"],
    )
    def test_escaping_or_absolute_paths_are_refused(self, fs_root: FsRoot, relative: str) -> None:
        with pytest.raises(SeraphimError) as exc:
            fs_root.resolve(relative)
        assert exc.value.code in (ErrorCode.FS_PATH_DENIED,)

    def test_traversal_read_never_returns_outside_content(self, fs_root: FsRoot) -> None:
        result = _call(_registry(fs_root), "tool.fs.read_file", path="../outside/secret_outside.txt")
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.FS_PATH_DENIED
        assert result.output is None
        assert "OUTSIDE" not in str(result.to_dict())

    def test_traversal_write_does_not_create_outside_file(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        result = _call(_registry(fs_root), "tool.fs.write_file", path="../escape.txt", text="x")
        assert result.status is CallStatus.FAILED
        assert not (sandbox["root"].parent / "escape.txt").exists()

    def test_reserved_device_name_is_refused(self, fs_root: FsRoot) -> None:
        with pytest.raises(SeraphimError):
            fs_root.resolve("CON.txt")


class TestJunctionAndSymlinkEscape:
    def test_junction_to_outside_is_refused_on_read(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        _make_junction(sandbox["root"] / "j", sandbox["outside"])
        result = _call(_registry(fs_root), "tool.fs.read_file", path="j/secret_outside.txt")
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.FS_PATH_DENIED
        assert "OUTSIDE" not in str(result.to_dict())

    def test_junction_to_outside_is_refused_on_write(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        _make_junction(sandbox["root"] / "j", sandbox["outside"])
        result = _call(_registry(fs_root), "tool.fs.write_file", path="j/new.txt", text="x")
        assert result.status is CallStatus.FAILED
        assert not (sandbox["outside"] / "new.txt").exists()

    def test_junction_is_not_listed_as_entry_target(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        _make_junction(sandbox["root"] / "j", sandbox["outside"])
        listing = fs_ops.list_dir(fs_root, ".")
        kinds = {e["name"]: e["kind"] for e in listing["entries"]}
        assert kinds["j"] == "link"

    def test_search_does_not_follow_junction(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        _make_junction(sandbox["root"] / "j", sandbox["outside"])
        result = fs_ops.search_text(fs_root, ".", "OUTSIDE")
        assert result["matches"] == []

    def test_symlink_to_outside_is_refused(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        _make_symlink(sandbox["root"] / "s", sandbox["outside"])
        with pytest.raises(SeraphimError) as exc:
            fs_root.resolve("s/secret_outside.txt")
        assert exc.value.code == ErrorCode.FS_PATH_DENIED


class TestSecretPaths:
    @pytest.mark.parametrize(
        "relative",
        [".env", "config/.env.local", ".git/config", "deep/nested/.ssh/id_rsa", "keys/server.pem", "a/secrets/x.txt", "my_token.txt", "vault/credentials.json"],
    )
    def test_secret_component_at_any_depth_is_refused(self, fs_root: FsRoot, relative: str) -> None:
        with pytest.raises(SeraphimError) as exc:
            fs_root.resolve(relative, must_exist=False)
        assert exc.value.code == ErrorCode.FS_PATH_DENIED

    def test_secret_directory_is_hidden_from_listing(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        (sandbox["root"] / ".git").mkdir()
        (sandbox["root"] / ".git" / "config").write_text("[core]", encoding="utf-8")
        names = {e["name"] for e in fs_ops.list_dir(fs_root, ".")["entries"]}
        assert ".git" not in names and "notes.txt" in names

    def test_secret_directory_is_skipped_by_search(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        (sandbox["root"] / "nested" / "secrets").mkdir(parents=True)
        (sandbox["root"] / "nested" / "secrets" / "plan.txt").write_text("needle inside secret", encoding="utf-8")
        result = fs_ops.search_text(fs_root, ".", "needle")
        assert all("secret" not in m["path"] for m in result["matches"])
        assert [m["path"] for m in result["matches"]] == ["notes.txt"]

    def test_secret_file_read_is_refused(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        (sandbox["root"] / ".env").write_text("TOKEN=abc", encoding="utf-8")
        result = _call(_registry(fs_root), "tool.fs.read_file", path=".env")
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.FS_PATH_DENIED
        assert "TOKEN" not in str(result.to_dict())


class TestSizeLimits:
    def test_too_large_read_is_refused(self, fs_root: FsRoot, sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fs_ops, "MAX_READ_BYTES", 16)
        (sandbox["root"] / "big.txt").write_text("x" * 64, encoding="utf-8")
        with pytest.raises(SeraphimError) as exc:
            fs_ops.read_file(fs_root, "big.txt")
        assert exc.value.code == ErrorCode.FS_TOO_LARGE

    def test_too_large_write_is_refused_and_nothing_is_written(self, fs_root: FsRoot, sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fs_ops, "MAX_WRITE_BYTES", 8)
        with pytest.raises(SeraphimError) as exc:
            fs_ops.write_file(fs_root, "new.txt", "x" * 9)
        assert exc.value.code == ErrorCode.FS_TOO_LARGE
        assert not (sandbox["root"] / "new.txt").exists()

    def test_search_stops_at_match_limit(self, fs_root: FsRoot, sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fs_ops, "MAX_SEARCH_MATCHES", 3)
        (sandbox["root"] / "many.txt").write_text("hit\n" * 10, encoding="utf-8")
        result = fs_ops.search_text(fs_root, ".", "hit")
        assert len(result["matches"]) == 3 and result["truncated"] is True


class TestAtomicWrite:
    def test_write_replaces_content_and_leaves_no_temp_file(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        fs_ops.write_file(fs_root, "notes.txt", "replaced")
        assert (sandbox["root"] / "notes.txt").read_text(encoding="utf-8") == "replaced"
        assert not [p for p in sandbox["root"].iterdir() if p.name.startswith(".seraphim-")]

    def test_failure_during_replace_keeps_original_file(self, fs_root: FsRoot, sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        def broken_replace(src: Any, dst: Any) -> None:
            raise OSError("disk gone")

        monkeypatch.setattr(fs_ops.os, "replace", broken_replace)
        with pytest.raises(SeraphimError) as exc:
            fs_ops.write_file(fs_root, "notes.txt", "new content")
        assert exc.value.code == ErrorCode.FS_IO_FAILED
        assert (sandbox["root"] / "notes.txt").read_text(encoding="utf-8") == "alpha\nneedle here\n"
        assert not [p for p in sandbox["root"].iterdir() if p.name.startswith(".seraphim-")]

    def test_failure_during_write_leaves_no_partial_file(self, fs_root: FsRoot, sandbox: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
        real_fsync = os.fsync

        def failing_fsync(fd: int) -> None:
            raise OSError("fsync failed")

        monkeypatch.setattr(fs_ops.os, "fsync", failing_fsync)
        with pytest.raises(SeraphimError) as exc:
            fs_ops.write_file(fs_root, "partial.txt", "half")
        monkeypatch.setattr(fs_ops.os, "fsync", real_fsync)
        assert exc.value.code == ErrorCode.FS_IO_FAILED
        assert not (sandbox["root"] / "partial.txt").exists()
        assert not [p for p in sandbox["root"].iterdir() if p.name.startswith(".seraphim-")]


class TestDenialAndErrors:
    def test_without_allow_rule_nothing_runs(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        deny = make_gate(PolicyEngine(build_policy_set(())), actor="test")
        result = _call(_registry(fs_root), "tool.fs.write_file", gate=deny, path="x.txt", text="x")
        assert result.status is CallStatus.REJECTED
        assert not (sandbox["root"] / "x.txt").exists()

    def test_read_only_user_rule_cannot_write(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        read_only = make_gate(
            PolicyEngine(
                build_policy_set(
                    (PolicyRule(rule_id="aegis.user.r", outcome="ALLOW", source="user", tool_pattern="tool.fs.*", side_effects=("read",)),)
                )
            ),
            actor="test",
        )
        result = _call(_registry(fs_root), "tool.fs.write_file", gate=read_only, path="x.txt", text="x")
        assert result.status is CallStatus.REJECTED
        assert not (sandbox["root"] / "x.txt").exists()

    def test_write_into_read_only_directory_is_normalized(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        locked = sandbox["root"] / "locked"
        locked.mkdir()
        os.chmod(locked, 0o555)
        try:
            result = _call(_registry(fs_root), "tool.fs.write_file", path="locked/x.txt", text="x")
        finally:
            os.chmod(locked, 0o755)
        if os.access(locked, os.W_OK):
            pytest.skip("host ignores directory write bits")
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.FS_IO_FAILED
        assert str(sandbox["root"]) not in str(result.to_dict())

    def test_missing_file_is_normalized_not_found(self, fs_root: FsRoot) -> None:
        result = _call(_registry(fs_root), "tool.fs.read_file", path="missing.txt")
        assert result.status is CallStatus.FAILED
        assert result.error is not None and result.error.code == ErrorCode.FS_NOT_FOUND

    def test_non_utf8_file_is_normalized(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        (sandbox["root"] / "bin.dat").write_bytes(b"\xff\xfe\x00bad")
        result = _call(_registry(fs_root), "tool.fs.read_file", path="bin.dat")
        assert result.error is not None and result.error.code in (ErrorCode.FS_IO_FAILED,)


class TestDeleteAndMove:
    def test_delete_without_destructive_allow_is_refused(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        result = _call(_registry(fs_root), "tool.fs.delete_file", path="notes.txt")
        assert result.status is CallStatus.REJECTED
        assert (sandbox["root"] / "notes.txt").exists()

    def test_destructive_call_still_needs_confirmation_even_with_user_allow(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        result = _call(_registry(fs_root), "tool.fs.delete_file", gate=_gate(destructive=True), path="notes.txt")
        assert result.status is CallStatus.REJECTED
        assert result.error is not None and "confirmation" in result.error.safe_message
        assert (sandbox["root"] / "notes.txt").exists()

    def test_delete_helper_moves_file_into_trash(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        out = fs_ops.delete_path(fs_root, "notes.txt")
        assert not (sandbox["root"] / "notes.txt").exists()
        assert (sandbox["root"] / out["trashed_to"]).exists()

    def test_delete_root_is_refused(self, fs_root: FsRoot) -> None:
        with pytest.raises(SeraphimError):
            fs_ops.delete_path(fs_root, ".")

    def test_move_inside_root_works(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        fs_ops.move_path(fs_root, "notes.txt", "moved.txt")
        assert (sandbox["root"] / "moved.txt").exists() and not (sandbox["root"] / "notes.txt").exists()

    def test_move_outside_root_is_refused(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        with pytest.raises(SeraphimError):
            fs_ops.move_path(fs_root, "notes.txt", "../stolen.txt")
        assert (sandbox["root"] / "notes.txt").exists()

    def test_create_dir_then_write_inside(self, fs_root: FsRoot, sandbox: dict[str, Path]) -> None:
        registry = _registry(fs_root)
        assert _call(registry, "tool.fs.create_dir", path="docs").status is CallStatus.SUCCEEDED
        assert _call(registry, "tool.fs.write_file", path="docs/a.txt", text="hi").status is CallStatus.SUCCEEDED
        assert (sandbox["root"] / "docs" / "a.txt").read_text(encoding="utf-8") == "hi"


class TestRootValidation:
    def test_missing_root_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SeraphimError) as exc:
            FsRoot(tmp_path / "nope")
        assert exc.value.code == ErrorCode.FS_NOT_FOUND
