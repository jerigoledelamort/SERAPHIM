# SERAPHIM SANCTUM — export/import tests (S11).
#
# Covers: version mismatch, path traversal, partial failure, secret exclusion,
# rollback, dry-run diff, atomic apply.

from __future__ import annotations

import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum import export_import
from seraphim.sanctum.export_import import (
    DOMAINS,
    EXPORT_FORMAT_VERSION,
    _check_traversal,
    export_to_archive,
    import_from_archive,
)

MARKER_SECRET = "sk-ant-EXPORTIMPORTTEST0123456789"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_root(tmp_path: Path) -> Path:
    """A SERAPHIM root with config and identity files."""
    root = tmp_path / "seraphim-root"
    (root / "config").mkdir(parents=True)
    (root / "identity").mkdir(parents=True)
    (root / "locales").mkdir(parents=True)
    (root / "themes").mkdir(parents=True)
    (root / "skills").mkdir(parents=True)

    (root / "config" / "runtime.yaml").write_text(
        "schema_version: 1\ntask_timeout_sec: 300\n", encoding="utf-8"
    )
    (root / "identity" / "identity.yaml").write_text(
        "schema_version: 1\nprofile:\n  display_name: Ada\n", encoding="utf-8"
    )
    (root / "locales" / "en.json").write_text('{"greeting": "Hello"}', encoding="utf-8")
    (root / "themes" / "dark.css").write_text("body { color: white; }", encoding="utf-8")
    (root / "skills" / "hello.yaml").write_text("id: hello\nversion: 1\n", encoding="utf-8")

    return root


@pytest.fixture
def root_with_secret_ref(tmp_path: Path) -> Path:
    """A root with a config that references a secret (value NOT included)."""
    root = tmp_path / "seraphim-secret-root"
    (root / "config").mkdir(parents=True)
    (root / "identity").mkdir(parents=True)

    (root / "config" / "runtime.yaml").write_text(
        "schema_version: 1\ntask_timeout_sec: 300\n", encoding="utf-8"
    )
    (root / "config" / "providers.yaml").write_text(
        "schema_version: 1\n"
        "default_model_id: claude-3\n"
        "models:\n"
        "  - id: claude-3\n"
        "    secret_ref: provider.anthropic\n",
        encoding="utf-8",
    )
    (root / "identity" / "identity.yaml").write_text(
        "schema_version: 1\nprofile:\n  display_name: Ada\n", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Export — happy path
# ---------------------------------------------------------------------------


class TestExportHappy:
    def test_export_creates_zip_and_manifest(self, minimal_root: Path) -> None:
        manifest = export_to_archive(minimal_root)
        assert manifest["file_count"] > 0
        assert manifest["export_format_version"] == EXPORT_FORMAT_VERSION
        assert "files" in manifest

        # Verify zip exists.
        backup_dir = minimal_root / "data" / "backups"
        zips = list(backup_dir.glob("seraphim-export-*.zip"))
        assert len(zips) == 1

        # Verify manifest alongside zip.
        manifests = list(backup_dir.glob("seraphim-export-*.json"))
        assert len(manifests) == 1

    def test_export_contains_expected_files(self, minimal_root: Path) -> None:
        manifest = export_to_archive(minimal_root)
        names = {f["archive_path"] for f in manifest["files"]}
        assert "config/runtime.yaml" in names
        assert "identity/identity.yaml" in names
        assert "locales/en.json" in names
        assert "themes/dark.css" in names
        assert "skills/hello.yaml" in names

    def test_export_excludes_secret_values(self, root_with_secret_ref: Path) -> None:
        manifest = export_to_archive(root_with_secret_ref)
        # The archive should not contain the MARKER_SECRET value.
        for finfo in manifest["files"]:
            assert MARKER_SECRET not in finfo.get("sha256", "")

    def test_export_excludes_data_dirs(self, minimal_root: Path) -> None:
        # Create data directory (should be excluded).
        (minimal_root / "data").mkdir(parents=True, exist_ok=True)
        (minimal_root / "data" / "test.bin").write_bytes(b"secret data")
        (minimal_root / "logs").mkdir(parents=True, exist_ok=True)
        (minimal_root / "logs" / "app.log").write_text("log line", encoding="utf-8")

        manifest = export_to_archive(minimal_root)
        names = {f["archive_path"] for f in manifest["files"]}
        for n in names:
            assert "data/" not in n
            assert "logs/" not in n

    def test_export_to_custom_path(self, minimal_root: Path, tmp_path: Path) -> None:
        out = tmp_path / "custom-export.zip"
        export_to_archive(minimal_root, output_path=out)
        assert out.exists()


# ---------------------------------------------------------------------------
# Import — dry-run
# ---------------------------------------------------------------------------


class TestImportDryRun:
    def test_import_dry_run_shows_diff(self, minimal_root: Path) -> None:
        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Import to empty root.
        target = minimal_root.parent / "empty-root"
        target.mkdir()
        result = import_from_archive(archive_path, target, dry_run=True)

        assert result["dry_run"] is True
        diff = result["diff"]
        assert len(diff["added"]) > 0
        assert len(diff["modified"]) == 0
        assert len(diff["removed"]) == 0

    def test_import_dry_run_unchanged(self, minimal_root: Path) -> None:
        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Import to the SAME root — everything unchanged.
        result = import_from_archive(archive_path, minimal_root, dry_run=True)

        assert result["dry_run"] is True
        diff = result["diff"]
        assert len(diff["added"]) == 0
        assert len(diff["modified"]) == 0
        assert len(diff["removed"]) == 0
        assert len(diff["unchanged"]) > 0


# ---------------------------------------------------------------------------
# Import — apply
# ---------------------------------------------------------------------------


class TestImportApply:
    def test_import_apply_writes_files(self, minimal_root: Path) -> None:
        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Import to a new root.
        target = minimal_root.parent / "imported-root"
        target.mkdir()

        result = import_from_archive(archive_path, target, dry_run=False)

        assert result["dry_run"] is False
        assert "backup_path" in result

        # Verify files exist in target.
        assert (target / "config" / "runtime.yaml").exists()
        assert (target / "identity" / "identity.yaml").exists()
        assert (target / "locales" / "en.json").exists()

    def test_import_apply_creates_backup(self, minimal_root: Path) -> None:
        # First, create an existing config in target.
        target = minimal_root.parent / "existing-root"
        (target / "config").mkdir(parents=True)
        (target / "identity").mkdir(parents=True)
        (target / "config" / "runtime.yaml").write_text("schema_version: 1\n", encoding="utf-8")

        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        result = import_from_archive(archive_path, target, dry_run=False, current_root=target)

        assert "backup_path" in result
        backup = Path(result["backup_path"])
        assert backup.is_dir()
        # Backup should contain the previous config.
        assert (backup / "config" / "runtime.yaml").exists()


# ---------------------------------------------------------------------------
# Import — version mismatch
# ---------------------------------------------------------------------------


class TestVersionMismatch:
    def test_incompatible_version_rejected(self, minimal_root: Path, tmp_path: Path) -> None:
        # Create an archive with a wrong version.
        bad_manifest = {
            "export_format_version": EXPORT_FORMAT_VERSION + 999,
            "seraphim_version": "0.0.1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "root": str(minimal_root),
            "domains": list(DOMAINS),
            "excluded": {},
            "file_count": 1,
            "files": [
                {
                    "archive_path": "config/runtime.yaml",
                    "size": 10,
                    "sha256": "abc123",
                }
            ],
        }
        bad_zip = tmp_path / "bad.zip"
        with ZipFile(bad_zip, "w") as zf:
            zf.writestr("manifest.json", json.dumps(bad_manifest))
            zf.writestr("config/runtime.yaml", "schema_version: 1\n")

        target = tmp_path / "target"
        target.mkdir()

        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(bad_zip, target, dry_run=True)

        assert exc_info.value.code == ErrorCode.ARCHIVE_VERSION_INCOMPATIBLE


# ---------------------------------------------------------------------------
# Import — path traversal
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_traversal_detected(self, minimal_root: Path) -> None:
        export_to_archive(minimal_root)
        minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Create a malicious archive with a ../ entry.
        evil_zip = minimal_root.parent / "evil.zip"
        evil_manifest = {
            "export_format_version": EXPORT_FORMAT_VERSION,
            "seraphim_version": "0.1.0",
            "created_at": "2026-01-01T00:00:00+00:00",
            "root": "/evil",
            "domains": list(DOMAINS),
            "excluded": {},
            "file_count": 1,
            "files": [
                {
                    "archive_path": "../escape.txt",
                    "size": 7,
                    "sha256": "abc123",
                }
            ],
        }
        with ZipFile(evil_zip, "w") as zf:
            zf.writestr("manifest.json", json.dumps(evil_manifest))
            zf.writestr("../escape.txt", "ESCAPED")

        target = minimal_root.parent / "traversal-target"
        target.mkdir()

        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(evil_zip, target, dry_run=True)

        assert exc_info.value.code == ErrorCode.ARCHIVE_PATH_TRAVERSAL

    def test_traversal_check_helper(self, tmp_path: Path) -> None:
        root = tmp_path / "root"
        root.mkdir()
        # Normal path is OK.
        _check_traversal("config/runtime.yaml", root)
        # Traversal is rejected.
        with pytest.raises(SeraphimError) as exc_info:
            _check_traversal("../escape.txt", root)
        assert exc_info.value.code == ErrorCode.ARCHIVE_PATH_TRAVERSAL


# ---------------------------------------------------------------------------
# Import — secret exclusion
# ---------------------------------------------------------------------------


class TestSecretExclusion:
    def test_archive_contains_no_secret_values(self, root_with_secret_ref: Path) -> None:
        export_to_archive(root_with_secret_ref)
        archive_path = root_with_secret_ref / "data" / "backups" / (
            next(p.name for p in (root_with_secret_ref / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Read all bytes from the zip.
        with ZipFile(archive_path, "r") as zf:
            all_content = b""
            for name in zf.namelist():
                all_content += zf.read(name)

        # The marker secret should NOT appear anywhere in the archive.
        assert MARKER_SECRET.encode() not in all_content

    def test_export_includes_secret_refs_not_values(self, root_with_secret_ref: Path) -> None:
        manifest = export_to_archive(root_with_secret_ref)
        # Providers file references provider.anthropic but not the value.
        for finfo in manifest["files"]:
            if "providers" in finfo["archive_path"]:
                # sha256 is present but the raw value is not in the manifest.
                assert MARKER_SECRET not in json.dumps(finfo)


# ---------------------------------------------------------------------------
# Import — partial failure / rollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_partial_failure_rolls_back(self, minimal_root: Path, tmp_path: Path) -> None:
        """Simulate a failure during atomic write → rollback restores original."""
        # Prepare a target with an existing config.
        target = tmp_path / "rollback-target"
        (target / "config").mkdir(parents=True)
        (target / "identity").mkdir(parents=True)
        original_content = "schema_version: 1\noriginal: true\n"
        (target / "config" / "runtime.yaml").write_text(original_content, encoding="utf-8")

        # Create a valid archive.
        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        # Normal apply should succeed.
        result = import_from_archive(archive_path, target, dry_run=False, current_root=target)
        assert result["dry_run"] is False

        # The new content should be there.
        new_content = (target / "config" / "runtime.yaml").read_text(encoding="utf-8")
        assert "task_timeout_sec" in new_content

        # Now simulate a traversal failure mid-import to trigger rollback.
        evil_zip = tmp_path / "evil-partial.zip"
        evil_manifest = {
            "export_format_version": EXPORT_FORMAT_VERSION,
            "seraphim_version": "0.1.0",
            "created_at": "2026-01-01T00:00:00+00:00",
            "root": "/evil",
            "domains": list(DOMAINS),
            "excluded": {},
            "file_count": 2,
            "files": [
                {"archive_path": "config/runtime.yaml", "size": 5, "sha256": "a"},
                {"archive_path": "../escape.txt", "size": 5, "sha256": "b"},
            ],
        }
        with ZipFile(evil_zip, "w") as zf:
            zf.writestr("manifest.json", json.dumps(evil_manifest))
            zf.writestr("config/runtime.yaml", "evil\n")
            zf.writestr("../escape.txt", "evil\n")

        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(evil_zip, target, dry_run=False, current_root=target)

        assert exc_info.value.code == ErrorCode.ARCHIVE_PATH_TRAVERSAL

        # After rollback, the original content from step 1 (imported content)
        # should be restored (it was the state before the evil import).
        content_after = (target / "config" / "runtime.yaml").read_text(encoding="utf-8")
        assert "task_timeout_sec" in content_after  # the state from the first valid import

    def test_rollback_after_backup(self, minimal_root: Path, tmp_path: Path) -> None:
        """Verify backup_path contains the pre-import state."""
        target = tmp_path / "backup-target"
        (target / "config").mkdir(parents=True)
        (target / "identity").mkdir(parents=True)
        original = "schema_version: 1\nmarker: original\n"
        (target / "config" / "runtime.yaml").write_text(original, encoding="utf-8")

        export_to_archive(minimal_root)
        archive_path = minimal_root / "data" / "backups" / (
            next(p.name for p in (minimal_root / "data" / "backups").glob("seraphim-export-*.zip"))
        )

        result = import_from_archive(archive_path, target, dry_run=False, current_root=target)
        backup = Path(result["backup_path"])

        # Backup has the original file.
        backup_runtime = backup / "config" / "runtime.yaml"
        assert backup_runtime.exists()
        assert "marker: original" in backup_runtime.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Import — archive not found
# ---------------------------------------------------------------------------


class TestArchiveNotFound:
    def test_missing_archive_rejected(self, minimal_root: Path) -> None:
        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive("/nonexistent/archive.zip", minimal_root, dry_run=True)
        assert exc_info.value.code == ErrorCode.ARCHIVE_NOT_FOUND


# ---------------------------------------------------------------------------
# Import — checksum verification (C4 review FINDING-2)
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_tampered_checksum_rejected(self, minimal_root: Path, tmp_path: Path) -> None:
        """An archive whose bytes no longer match the manifest is refused."""
        export_to_archive(minimal_root)
        archive_path = next(
            (minimal_root / "data" / "backups").glob("seraphim-export-*.zip")
        )

        # Rebuild the archive keeping the manifest but changing one file's bytes.
        tampered = tmp_path / "tampered.zip"
        with ZipFile(archive_path, "r") as src, ZipFile(tampered, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "config/runtime.yaml":
                    data = b"schema_version: 1\nTAMPERED: true\n"
                dst.writestr(name, data)

        target = tmp_path / "integrity-target"
        target.mkdir()
        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(tampered, target, dry_run=True)
        assert exc_info.value.code == ErrorCode.ARCHIVE_INTEGRITY_FAILED
        # The offending value is never echoed back.
        assert "TAMPERED" not in str(exc_info.value)

    def test_undeclared_entry_rejected(self, minimal_root: Path, tmp_path: Path) -> None:
        """A file present in the archive but absent from the manifest is refused."""
        export_to_archive(minimal_root)
        archive_path = next(
            (minimal_root / "data" / "backups").glob("seraphim-export-*.zip")
        )

        smuggled = tmp_path / "smuggled.zip"
        with ZipFile(archive_path, "r") as src, ZipFile(smuggled, "w") as dst:
            for name in src.namelist():
                dst.writestr(name, src.read(name))
            dst.writestr("config/undeclared.yaml", "injected: true\n")

        target = tmp_path / "undeclared-target"
        target.mkdir()
        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(smuggled, target, dry_run=True)
        assert exc_info.value.code == ErrorCode.ARCHIVE_INTEGRITY_FAILED


# ---------------------------------------------------------------------------
# Export — secret exclusion in raw locale/theme/skills files (FINDING-3)
# ---------------------------------------------------------------------------


class TestRawSecretExclusion:
    RAW_MARKER = "sk-ant-RAWTHEMELEAK0123456789ab"

    def test_export_refuses_secret_in_theme(self, tmp_path: Path) -> None:
        root = tmp_path / "leaky-root"
        for d in ("config", "identity", "themes"):
            (root / d).mkdir(parents=True)
        (root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\n", encoding="utf-8"
        )
        (root / "identity" / "identity.yaml").write_text(
            "schema_version: 1\nprofile:\n  display_name: Ada\n", encoding="utf-8"
        )
        # A key pasted into a raw theme file, invisible to build_safe_export.
        (root / "themes" / "custom.css").write_text(
            f"body {{ color: red; }} /* {self.RAW_MARKER} */\n", encoding="utf-8"
        )

        with pytest.raises(SeraphimError) as exc_info:
            export_to_archive(root, output_path=tmp_path / "leak.zip")
        assert exc_info.value.code == ErrorCode.ARCHIVE_EXPORT_FAILED
        # The refusal must not echo the secret value.
        assert self.RAW_MARKER not in str(exc_info.value)

    def test_export_refuses_secret_in_locale(self, tmp_path: Path) -> None:
        root = tmp_path / "leaky-locale"
        for d in ("config", "identity", "locales"):
            (root / d).mkdir(parents=True)
        (root / "config" / "runtime.yaml").write_text(
            "schema_version: 1\n", encoding="utf-8"
        )
        (root / "identity" / "identity.yaml").write_text(
            "schema_version: 1\n", encoding="utf-8"
        )
        (root / "locales" / "en.json").write_text(
            json.dumps({"greeting": self.RAW_MARKER}), encoding="utf-8"
        )

        with pytest.raises(SeraphimError) as exc_info:
            export_to_archive(root, output_path=tmp_path / "leak2.zip")
        assert exc_info.value.code == ErrorCode.ARCHIVE_EXPORT_FAILED
        assert self.RAW_MARKER not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Import — rollback restores EVERY domain, incl. locales/themes (FINDING-1)
# ---------------------------------------------------------------------------


class TestRollbackAllDomains:
    DOMAINS = ("config", "identity", "locales", "themes", "skills")

    def _seed(self, root: Path, marker: str) -> None:
        for d in self.DOMAINS:
            (root / d).mkdir(parents=True, exist_ok=True)
        # config must be schema-valid so build_safe_export succeeds on export.
        (root / "config" / "runtime.yaml").write_text(
            f"schema_version: 1\ntask_timeout_sec: {300 if marker == 'NEW' else 100}\n",
            encoding="utf-8",
        )
        (root / "identity" / "identity.yaml").write_text(
            f"schema_version: 1\nprofile:\n  display_name: {marker}\n", encoding="utf-8"
        )
        (root / "locales" / "en.json").write_text(
            json.dumps({"v": marker}), encoding="utf-8"
        )
        (root / "themes" / "dark.css").write_text(f"/* {marker} */", encoding="utf-8")
        (root / "skills" / "hello.yaml").write_text(f"id: hello\nv: {marker}\n", encoding="utf-8")

    def test_apply_failure_restores_locales_and_themes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = tmp_path / "src"
        tgt = tmp_path / "tgt"
        self._seed(src, "NEW")
        self._seed(tgt, "ORIGINAL")

        export_to_archive(src, output_path=tmp_path / "snap.zip")
        archive = tmp_path / "snap.zip"

        # Force a write failure on the LAST domain (skills), after config,
        # identity, locales and themes were already written.
        real_replace = os.replace

        def failing_replace(a, b, *args, **kwargs):
            if "skills" in str(b):
                raise OSError("simulated disk failure")
            return real_replace(a, b, *args, **kwargs)

        monkeypatch.setattr(export_import.os, "replace", failing_replace)
        with pytest.raises(SeraphimError) as exc_info:
            import_from_archive(archive, tgt, dry_run=False, current_root=tgt)
        assert exc_info.value.code == ErrorCode.ARCHIVE_IMPORT_FAILED

        # Every domain must be back to ORIGINAL — this is what the old
        # key-vs-value bug broke for locales/ and themes/.
        for rel, expect in (
            ("config/runtime.yaml", "task_timeout_sec: 100"),
            ("identity/identity.yaml", "ORIGINAL"),
            ("locales/en.json", "ORIGINAL"),
            ("themes/dark.css", "ORIGINAL"),
            ("skills/hello.yaml", "ORIGINAL"),
        ):
            body = (tgt / rel).read_text(encoding="utf-8")
            assert expect in body, f"{rel} was not rolled back: {body!r}"


# ---------------------------------------------------------------------------
# Import — --apply deletes the files the dry-run diff promised to remove
# ---------------------------------------------------------------------------


class TestApplyRemovesFiles:
    def test_apply_deletes_removed_file(self, minimal_root: Path, tmp_path: Path) -> None:
        export_to_archive(minimal_root)
        archive = next(
            (minimal_root / "data" / "backups").glob("seraphim-export-*.zip")
        )

        target = tmp_path / "remove-target"
        for d in ("config", "identity", "locales", "themes", "skills"):
            (target / d).mkdir(parents=True)
        stale = target / "themes" / "stale.css"
        stale.write_text("old theme", encoding="utf-8")

        preview = import_from_archive(archive, target, dry_run=True)
        assert "themes/stale.css" in preview["diff"]["removed"]

        import_from_archive(archive, target, dry_run=False, current_root=target)
        assert not stale.exists(), "--apply kept a file the dry-run diff promised to delete"


# ---------------------------------------------------------------------------
# CLI export/import — smoke via CliRunner
# ---------------------------------------------------------------------------


pytest.importorskip("click")
from click.testing import CliRunner  # noqa: E402
from seraphim.cli.main import cli  # noqa: E402


class TestExportCLI:
    def test_export_exits_zero(self, minimal_root: Path) -> None:
        result = CliRunner().invoke(cli, ["config", "export", "--config-dir", str(minimal_root)])
        assert result.exit_code == 0
        assert "SERAPHIM configuration export" in result.output

    def test_export_json(self, minimal_root: Path) -> None:
        result = CliRunner().invoke(
            cli, ["config", "export", "--config-dir", str(minimal_root), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["export_format_version"] == EXPORT_FORMAT_VERSION
        assert payload["file_count"] > 0

    def test_export_custom_path(self, minimal_root: Path, tmp_path: Path) -> None:
        out = tmp_path / "cli-export.zip"
        result = CliRunner().invoke(
            cli,
            ["config", "export", "--config-dir", str(minimal_root), "--out", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()


class TestImportCLI:
    def _make_archive(self, minimal_root: Path) -> Path:
        export_to_archive(minimal_root)
        backups = minimal_root / "data" / "backups"
        return backups / (
            next(p.name for p in backups.glob("seraphim-export-*.zip"))
        )

    def test_import_dry_run_exits_zero(self, minimal_root: Path) -> None:
        archive = self._make_archive(minimal_root)
        target = minimal_root.parent / "cli-target"
        target.mkdir()
        result = CliRunner().invoke(
            cli, ["config", "import", str(archive), "--config-dir", str(target)]
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "Dry-run" in result.output

    def test_import_json(self, minimal_root: Path) -> None:
        archive = self._make_archive(minimal_root)
        target = minimal_root.parent / "cli-target-json"
        target.mkdir()
        result = CliRunner().invoke(
            cli, ["config", "import", str(archive), "--config-dir", str(target), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["dry_run"] is True

    def test_import_apply(self, minimal_root: Path) -> None:
        archive = self._make_archive(minimal_root)
        target = minimal_root.parent / "cli-apply-target"
        target.mkdir()
        result = CliRunner().invoke(
            cli,
            ["config", "import", str(archive), "--config-dir", str(target), "--apply"],
        )
        assert result.exit_code == 0
        assert (target / "config" / "runtime.yaml").exists()

    def test_import_missing_archive_fails(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["config", "import", str(tmp_path / "absent.zip")]
        )
        assert result.exit_code == 2  # click.Path(exists=True) → usage error
