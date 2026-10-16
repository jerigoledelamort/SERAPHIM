# SERAPHIM SANCTUM — secret storage tests (S09).
#
# Acceptance: API keys are not stored in config/SQLite/logs; the platform store
# is used, and an unsupported platform fails closed instead of writing plaintext.
# TB-7: secrets must never appear in logs or artifacts.

from __future__ import annotations

import json
import logging
import sys
from io import StringIO
from pathlib import Path

import pytest
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.contracts.sanitization import known_secret_count, sanitize_text
from seraphim.sanctum.secrets import (
    MASK_PREFIX,
    DPAPISecretStore,
    InMemorySecretStore,
    UnavailableSecretStore,
    create_secret_store,
    dpapi_available,
    looks_like_secret,
    mask_secret,
    provider_auth_error,
    validate_secret_ref,
)

MARKER_SECRET = "SERAPHIM_TEST_SECRET_xyz789"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


# ---------------------------------------------------------------------------
# Reference validation
# ---------------------------------------------------------------------------


class TestSecretRefValidation:
    @pytest.mark.parametrize(
        "ref",
        ["provider.openai", "anthropic", "a", "provider-1_key.v2", "x" * 64],
    )
    def test_valid_refs_accepted(self, ref: str) -> None:
        assert validate_secret_ref(ref) == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            ".hidden",
            "..",
            "trailing-",
            "-leading",
            "with/slash",
            "with\backslash",
            "with space",
            "UPPERCASE",
            "x" * 65,
            "con",
            "com1",
        ],
    )
    def test_invalid_refs_rejected(self, ref: str) -> None:
        with pytest.raises(SeraphimError) as exc:
            validate_secret_ref(ref)
        assert exc.value.code == ErrorCode.SECRET_REF_INVALID

    def test_non_string_ref_rejected(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            validate_secret_ref(42)  # type: ignore[arg-type]
        assert exc.value.code == ErrorCode.SECRET_REF_INVALID

    def test_error_message_does_not_echo_the_ref(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            validate_secret_ref("with space")
        assert "with space" not in exc.value.safe_message


class TestMasking:
    def test_mask_shows_only_tail(self) -> None:
        masked = mask_secret(MARKER_SECRET)
        assert masked == "****z789"
        assert MARKER_SECRET not in masked

    def test_short_value_fully_masked(self) -> None:
        assert mask_secret("abc") == MASK_PREFIX

    def test_non_string_masked(self) -> None:
        assert mask_secret(None) == MASK_PREFIX  # type: ignore[arg-type]


class TestLooksLikeSecret:
    @pytest.mark.parametrize(
        "value",
        ["sk-abcdef1234567890abcdef", "sk-ant-api03-abcdefghijklmnop", "AKIAIOSFODNN7EXAMPLE"],
    )
    def test_literal_keys_detected(self, value: str) -> None:
        assert looks_like_secret(value) is True

    @pytest.mark.parametrize("value", ["provider.openai", "anthropic", "", "my-key-1"])
    def test_references_not_flagged(self, value: str) -> None:
        assert looks_like_secret(value) is False


# ---------------------------------------------------------------------------
# In-memory backend (interface behaviour, platform independent)
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    def test_set_get_has_delete_roundtrip(self) -> None:
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        assert store.has("provider.openai") is True
        assert store.get("provider.openai") == MARKER_SECRET
        assert store.delete("provider.openai") is True
        assert store.has("provider.openai") is False
        assert store.delete("provider.openai") is False

    def test_missing_ref_raises_secret_not_found(self) -> None:
        store = InMemorySecretStore()
        with pytest.raises(SeraphimError) as exc:
            store.get("provider.absent")
        assert exc.value.code == ErrorCode.SECRET_NOT_FOUND

    def test_invalid_ref_rejected_on_every_operation(self) -> None:
        store = InMemorySecretStore()
        for call in (
            lambda: store.set("bad ref", MARKER_SECRET),
            lambda: store.get("bad ref"),
            lambda: store.has("bad ref"),
            lambda: store.delete("bad ref"),
        ):
            with pytest.raises(SeraphimError) as exc:
                call()
            assert exc.value.code == ErrorCode.SECRET_REF_INVALID

    def test_empty_value_rejected(self) -> None:
        store = InMemorySecretStore()
        with pytest.raises(SeraphimError) as exc:
            store.set("provider.openai", "   ")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_rotate_replaces_value(self) -> None:
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        store.rotate("provider.openai", "NEW-VALUE-12345678")
        assert store.get("provider.openai") == "NEW-VALUE-12345678"

    def test_rotate_missing_ref_refused(self) -> None:
        store = InMemorySecretStore()
        with pytest.raises(SeraphimError) as exc:
            store.rotate("provider.absent", "NEW-VALUE-12345678")
        assert exc.value.code == ErrorCode.SECRET_NOT_FOUND

    def test_list_and_statuses_never_expose_values(self) -> None:
        store = InMemorySecretStore()
        store.set("b.ref", MARKER_SECRET)
        store.set("a.ref", MARKER_SECRET)
        assert store.list_refs() == ["a.ref", "b.ref"]
        serialized = json.dumps([s.to_dict() for s in store.statuses()])
        assert MARKER_SECRET not in serialized
        assert "a.ref" in serialized

    def test_info_never_exposes_values(self) -> None:
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        assert MARKER_SECRET not in json.dumps(store.info.to_dict())


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_unsupported_platform_returns_unavailable_store(self) -> None:
        store = create_secret_store("/tmp/root", platform="linux")
        assert isinstance(store, UnavailableSecretStore)
        assert store.backend == "unavailable"

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.set("provider.openai", MARKER_SECRET),
            lambda s: s.get("provider.openai"),
            lambda s: s.delete("provider.openai"),
        ],
    )
    def test_operations_raise_store_unavailable(self, call) -> None:
        store = UnavailableSecretStore("no backend on this platform")
        with pytest.raises(SeraphimError) as exc:
            call(store)
        assert exc.value.code == ErrorCode.SECRET_STORE_UNAVAILABLE

    def test_no_plaintext_fallback_exists(self) -> None:
        # The factory must never silently pick a plaintext file backend.
        for platform in ("linux", "darwin", "freebsd"):
            store = create_secret_store("/tmp/root", platform=platform)
            assert store.backend == "unavailable"

    def test_unknown_backend_name_rejected(self) -> None:
        with pytest.raises(SeraphimError) as exc:
            create_secret_store("/tmp/root", backend="plaintext")
        assert exc.value.code == ErrorCode.VALIDATION_FAILED

    def test_memory_backend_is_explicit_only(self) -> None:
        # Not selected by default on any platform, even Windows.
        store = create_secret_store("/tmp/root", platform="win32", backend="memory")
        assert isinstance(store, InMemorySecretStore)


# ---------------------------------------------------------------------------
# Windows DPAPI backend
# ---------------------------------------------------------------------------


@windows_only
class TestDPAPIStore:
    @pytest.fixture
    def store(self, test_root: Path) -> DPAPISecretStore:
        test_root.mkdir(parents=True, exist_ok=True)
        return DPAPISecretStore(test_root)

    def test_dpapi_is_available_on_windows(self) -> None:
        available, reason = dpapi_available()
        assert available, reason

    def test_roundtrip(self, store: DPAPISecretStore) -> None:
        store.set("provider.openai", MARKER_SECRET)
        assert store.get("provider.openai") == MARKER_SECRET

    def test_ciphertext_file_contains_no_plaintext(self, store: DPAPISecretStore) -> None:
        store.set("provider.openai", MARKER_SECRET)
        raw = store.path_for("provider.openai").read_bytes()
        assert MARKER_SECRET.encode("utf-8") not in raw

    def test_ciphertext_lives_inside_root(self, store: DPAPISecretStore, test_root: Path) -> None:
        store.set("provider.openai", MARKER_SECRET)
        path = store.path_for("provider.openai")
        assert path.is_file()
        assert test_root in path.parents
        assert path.parent.name == "secrets"
        assert path.name == "provider.openai.bin"

    def test_info_reports_encrypted_location(self, store: DPAPISecretStore, test_root: Path) -> None:
        info = store.info.to_dict()
        assert info["backend"] == "dpapi"
        assert info["encrypted_at_rest"] is True
        assert info["persistent"] is True
        assert MARKER_SECRET not in json.dumps(info)

    def test_missing_ref_raises_secret_not_found(self, store: DPAPISecretStore) -> None:
        with pytest.raises(SeraphimError) as exc:
            store.get("provider.absent")
        assert exc.value.code == ErrorCode.SECRET_NOT_FOUND

    def test_list_delete_and_rotate(self, store: DPAPISecretStore) -> None:
        store.set("b.ref", MARKER_SECRET)
        store.set("a.ref", MARKER_SECRET)
        assert store.list_refs() == ["a.ref", "b.ref"]
        store.rotate("a.ref", "ROTATED-VALUE-99887766")
        assert store.get("a.ref") == "ROTATED-VALUE-99887766"
        assert store.delete("a.ref") is True
        assert store.list_refs() == ["b.ref"]

    def test_list_ignores_unrelated_files(self, store: DPAPISecretStore) -> None:
        store.set("a.ref", MARKER_SECRET)
        (store.path_for("a.ref").parent / "notes.txt").write_text("x", encoding="utf-8")
        assert store.list_refs() == ["a.ref"]

    def test_foreign_file_rejected(self, store: DPAPISecretStore) -> None:
        store.set("a.ref", MARKER_SECRET)
        store.path_for("a.ref").write_bytes(b"NOT-A-SERAPHIM-FILE")
        with pytest.raises(SeraphimError) as exc:
            store.get("a.ref")
        assert exc.value.code == ErrorCode.SECRET_ACCESS_DENIED

    def test_rotate_does_not_create_missing_ref(self, store: DPAPISecretStore) -> None:
        with pytest.raises(SeraphimError) as exc:
            store.rotate("provider.absent", MARKER_SECRET)
        assert exc.value.code == ErrorCode.SECRET_NOT_FOUND
        assert store.list_refs() == []

    def test_masked_display(self, store: DPAPISecretStore) -> None:
        store.set("provider.openai", MARKER_SECRET)
        masked = store.masked("provider.openai")
        assert MARKER_SECRET not in masked
        assert masked.startswith(MASK_PREFIX)


# ---------------------------------------------------------------------------
# Secrets must not reach logs
# ---------------------------------------------------------------------------


class TestSecretLogging:
    def _capture(self, logger_name: str) -> tuple[StringIO, logging.Handler]:
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        target = logging.getLogger(logger_name)
        target.addHandler(handler)
        target.setLevel(logging.DEBUG)
        return stream, handler

    def test_store_operations_do_not_log_values(self, test_root: Path) -> None:
        test_root.mkdir(parents=True, exist_ok=True)
        stream, handler = self._capture("seraphim")
        try:
            store = InMemorySecretStore()
            store.set("provider.openai", MARKER_SECRET)
            store.get("provider.openai")
            store.masked("provider.openai")
            store.rotate("provider.openai", MARKER_SECRET + "2")
            store.delete("provider.openai")
        finally:
            logging.getLogger("seraphim").removeHandler(handler)
        assert MARKER_SECRET not in stream.getvalue()

    def test_errors_do_not_carry_the_value(self) -> None:
        store = InMemorySecretStore()
        with pytest.raises(SeraphimError) as exc:
            store.get("provider.absent")
        serialized = json.dumps(exc.value.to_diagnostic_dict())
        assert MARKER_SECRET not in serialized

    def test_error_details_with_read_value_are_scrubbed(self) -> None:
        # A value read from the store is registered process-wide, so even a plain
        # error that carries it under a neutral key cannot leak it.
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        read_back = store.get("provider.openai")
        err = SeraphimError(
            code=ErrorCode.PROVIDER_AUTH_FAILED,
            component="model_layer.openai",
            safe_message=f"401 Unauthorized for {read_back}",
            details={"note": read_back, "provider": "openai"},
        )
        assert MARKER_SECRET not in json.dumps(err.to_diagnostic_dict())
        assert err.sanitized_details["provider"] == "openai"


class TestReadValuesAreRegistered:
    """S09 review F1: reading a secret registers it process-wide.

    This is what makes exact-value redaction structural rather than dependent on
    every sink remembering to pass the value in.
    """

    def test_in_memory_store_get_registers_value(self) -> None:
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        assert known_secret_count() == 0
        store.get("provider.openai")
        assert known_secret_count() == 1
        assert MARKER_SECRET not in sanitize_text(f"leaked: {MARKER_SECRET}")

    @windows_only
    def test_dpapi_store_get_registers_value(self, test_root: Path) -> None:
        test_root.mkdir(parents=True, exist_ok=True)
        store = DPAPISecretStore(test_root)
        store.set("provider.openai", MARKER_SECRET)
        store.get("provider.openai")
        assert known_secret_count() == 1
        assert MARKER_SECRET not in sanitize_text(f"leaked: {MARKER_SECRET}")

    def test_absent_ref_registers_nothing(self) -> None:
        store = InMemorySecretStore()
        with pytest.raises(SeraphimError):
            store.get("provider.absent")
        assert known_secret_count() == 0


class TestAuthErrorsDoNotLeak:
    """Acceptance: an auth error must not reveal the key value."""

    def test_provider_auth_error_hides_key_in_message(self) -> None:
        # The value has no recognizable format and sits under a neutral label, so
        # only exact-value redaction can remove it.  The store registers every
        # value it reads, which is what protects an error built by hand.
        store = InMemorySecretStore()
        store.set("provider.openai", MARKER_SECRET)
        read_back = store.get("provider.openai")
        err = SeraphimError(
            code=ErrorCode.PROVIDER_AUTH_FAILED,
            component="model_layer.openai",
            safe_message=f"401 Unauthorized for credential {read_back}",
            user_action_required=True,
            details={"note": read_back, "provider": "openai"},
        )
        for rendered in (
            str(err),
            json.dumps(err.to_dict()),
            json.dumps(err.to_diagnostic_dict()),
        ):
            assert MARKER_SECRET not in rendered

    def test_provider_auth_error_hides_key_in_bare_message(self) -> None:
        # A value whose format no pattern recognizes: the caller passes it in,
        # so the helper removes it by exact match.
        err = provider_auth_error(
            "openai",
            "provider.openai",
            status=401,
            key_value=MARKER_SECRET,
            detail=f"rejected credential {MARKER_SECRET}",
        )
        for rendered in (
            str(err),
            json.dumps(err.to_dict()),
            json.dumps(err.to_diagnostic_dict()),
        ):
            assert MARKER_SECRET not in rendered
        # The reference is reported so the user can fix the credential.
        assert err.sanitized_details["secret_ref"] == "provider.openai"
        assert err.sanitized_details["value_supplied"] is True

    def test_pattern_based_key_is_redacted_even_without_the_helper(self) -> None:
        # Known provider formats are caught by the sanitizer alone.
        literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
        err = SeraphimError(
            code=ErrorCode.PROVIDER_AUTH_FAILED,
            component="model_layer.anthropic",
            safe_message=f"401 Unauthorized for {literal}",
        )
        assert literal not in err.safe_message

    def test_auth_error_from_exception_is_scrubbed(self) -> None:
        literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
        exc = RuntimeError(f"auth failed with {literal}")
        err = SeraphimError.from_exception(exc, component="model_layer.anthropic")
        assert literal not in err.safe_message
        assert literal not in json.dumps(err.to_diagnostic_dict())
