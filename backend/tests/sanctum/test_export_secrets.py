# SERAPHIM SANCTUM — export-without-secrets and secret-ref config tests (S09).
#
# Acceptance: an export contains no active secrets; a config holds only a
# reference; a literal key pasted into a config is refused.  Spec §15,
# golden scenario §20.2 #18, CONTRACTS §4.4.

from __future__ import annotations

import json
from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import register_known_secret
from seraphim.sanctum.export import (
    build_safe_export,
    find_secret_material,
    verify_no_secrets,
)
from seraphim.sanctum.loader import load_config
from seraphim.sanctum.secrets import InMemorySecretStore

MARKER_SECRET = "SERAPHIM_TEST_SECRET_xyz789"
LITERAL_KEY = "sk-ant-api03-abcdefghijklmnopqrstuv"


def _write_providers(root: Path, models: list[dict]) -> None:
    import yaml

    config_dir = root / ".seraphim"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "providers.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "models": models}), encoding="utf-8"
    )


def _identity_dirs(tmp_path: Path) -> dict:
    return {
        "user_identity_dir": tmp_path / "user-identity",
        "workspace_identity_dir": tmp_path / "ws-identity",
    }


@pytest.fixture(autouse=True)
def _hermetic_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the loader away from any real user config on the machine."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


# ---------------------------------------------------------------------------
# Config holds only a reference
# ---------------------------------------------------------------------------


class TestSecretRefInConfig:
    def test_valid_secret_ref_accepted(self, test_root: Path) -> None:
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "secret_ref": "provider.anthropic",
                }
            ],
        )
        config = load_config(test_root)
        assert config.providers.models[0]["secret_ref"] == "provider.anthropic"

    def test_literal_api_key_in_config_rejected(self, test_root: Path) -> None:
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "secret_ref": LITERAL_KEY,
                }
            ],
        )
        with pytest.raises(SeraphimError) as exc:
            load_config(test_root)
        assert exc.value.code == ErrorCode.SECRET_REF_INVALID
        # The literal key must not be echoed back into the error.
        assert LITERAL_KEY not in exc.value.safe_message
        assert LITERAL_KEY not in json.dumps(exc.value.to_diagnostic_dict())

    def test_malformed_secret_ref_rejected(self, test_root: Path) -> None:
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "secret_ref": "Not A Ref",
                }
            ],
        )
        with pytest.raises(SeraphimError) as exc:
            load_config(test_root)
        assert exc.value.code == ErrorCode.SECRET_REF_INVALID

    def test_absent_secret_ref_is_allowed(self, test_root: Path) -> None:
        # A local provider needs no credential.
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [{"id": "m1", "provider": "local_ollama", "model_name": "llama3"}],
        )
        config = load_config(test_root)
        assert config.providers.models[0].get("secret_ref", "") == ""

    def test_unknown_credential_ref_key_is_still_rejected(self, test_root: Path) -> None:
        # The old field name is gone: an unknown key is not silently ignored.
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "credential_ref": "provider.anthropic",
                }
            ],
        )
        with pytest.raises(SeraphimError) as exc:
            load_config(test_root)
        assert exc.value.code == ErrorCode.CONFIG_SCHEMA_INVALID


# ---------------------------------------------------------------------------
# Export without secrets
# ---------------------------------------------------------------------------


class TestExportWithoutSecrets:
    @pytest.fixture
    def exported(self, test_root: Path, tmp_path: Path) -> tuple[dict, InMemorySecretStore]:
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "secret_ref": "provider.anthropic",
                }
            ],
        )
        store = InMemorySecretStore()
        store.set("provider.anthropic", MARKER_SECRET)
        payload = build_safe_export(test_root, secret_store=store, **_identity_dirs(tmp_path))
        return payload, store

    def test_export_contains_no_secret_value(self, exported) -> None:
        payload, _ = exported
        assert MARKER_SECRET not in json.dumps(payload)

    def test_export_contains_the_reference_instead(self, exported) -> None:
        payload, _ = exported
        assert payload["config"]["providers"]["models"][0]["secret_ref"] == "provider.anthropic"

    def test_export_secrets_section_excludes_values(self, exported) -> None:
        payload, _ = exported
        secrets_section = payload["secrets"]
        assert secrets_section["included"] is False
        assert secrets_section["refs"] == ["provider.anthropic"]
        assert MARKER_SECRET not in json.dumps(secrets_section)

    def test_export_has_no_machine_absolute_path(self, exported) -> None:
        payload, _ = exported
        location = payload["secrets"]["location"]
        assert not Path(location).is_absolute()

    def test_export_passes_its_own_verifier(self, exported) -> None:
        payload, _ = exported
        verify_no_secrets(payload, known_secrets=[MARKER_SECRET])

    def test_export_is_json_serializable(self, exported) -> None:
        payload, _ = exported
        assert isinstance(json.loads(json.dumps(payload)), dict)

    def test_export_with_a_planted_secret_is_detected(self, exported) -> None:
        payload, _ = exported
        payload["config"]["runtime"]["leaked"] = MARKER_SECRET
        with pytest.raises(SeraphimError) as exc:
            verify_no_secrets(payload, known_secrets=[MARKER_SECRET])
        assert exc.value.code == ErrorCode.DIAGNOSTIC_EXPORT_FAILED
        assert MARKER_SECRET not in exc.value.safe_message

    def test_export_with_planted_pattern_secret_is_detected(self, exported) -> None:
        payload, _ = exported
        payload["identity"]["personality"] = f"never print {LITERAL_KEY}"
        leaks = find_secret_material(payload)
        assert leaks
        assert all(LITERAL_KEY not in path for path in leaks)

    def test_find_secret_material_reports_paths_only(self) -> None:
        leaks = find_secret_material({"a": {"b": [MARKER_SECRET]}}, known_secrets=[MARKER_SECRET])
        assert leaks == ["$.a.b[0]"]

    def test_find_secret_material_detects_a_secret_used_as_key(self) -> None:
        # S09 review F4: keys are inspected too, and the key is not echoed back.
        leaks = find_secret_material({LITERAL_KEY: "value"})
        assert leaks == ["$.*"]
        assert all(LITERAL_KEY not in path for path in leaks)

    def test_find_secret_material_detects_registered_value_as_key(self) -> None:
        register_known_secret(MARKER_SECRET)
        leaks = find_secret_material({MARKER_SECRET: "value"})
        assert leaks == ["$.*"]
        assert all(MARKER_SECRET not in path for path in leaks)

    def test_find_secret_material_detects_value_inside_a_set(self) -> None:
        leaks = find_secret_material({"tags": {LITERAL_KEY}})
        assert leaks == ["$.tags[0]"]

    def test_export_scrubs_a_registered_secret_planted_in_identity(
        self, test_root: Path, tmp_path: Path
    ) -> None:
        """A value read into the process cannot reappear through identity text."""
        test_root.mkdir(parents=True, exist_ok=True)
        _write_providers(
            test_root,
            [
                {
                    "id": "m1",
                    "provider": "anthropic",
                    "model_name": "claude",
                    "secret_ref": "provider.anthropic",
                }
            ],
        )
        workspace_identity = tmp_path / "ws-identity"
        workspace_identity.mkdir(parents=True, exist_ok=True)
        (workspace_identity / "personality.md").write_text(
            f"never print {MARKER_SECRET}", encoding="utf-8"
        )
        store = InMemorySecretStore()
        store.set("provider.anthropic", MARKER_SECRET)
        store.get("provider.anthropic")  # registers the value process-wide

        payload = build_safe_export(test_root, secret_store=store, **_identity_dirs(tmp_path))

        assert MARKER_SECRET not in json.dumps(payload)

    def test_build_safe_export_refuses_when_the_sanitizer_is_bypassed(
        self, test_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The builder verifies its own output (S09 review F4)."""
        import seraphim.sanctum.export as export_module

        test_root.mkdir(parents=True, exist_ok=True)

        def _leaky(payload: dict) -> dict:
            payload["config"]["runtime"]["leaked"] = LITERAL_KEY
            return payload

        monkeypatch.setattr(export_module, "sanitize_export", _leaky)
        with pytest.raises(SeraphimError) as exc:
            build_safe_export(
                test_root, secret_store=InMemorySecretStore(), **_identity_dirs(tmp_path)
            )
        assert exc.value.code == ErrorCode.DIAGNOSTIC_EXPORT_FAILED
        assert LITERAL_KEY not in exc.value.safe_message
