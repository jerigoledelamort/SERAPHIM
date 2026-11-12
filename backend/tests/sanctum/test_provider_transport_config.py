"""S13: provider transport settings in the configuration.

Covers the fields added to ``providers.models[]`` so that an OpenAI-compatible
endpoint (URL, paths, auth scheme, headers, token-budget field, capability
declaration) is described by configuration rather than by source code, and the
loader's refusal to accept a literal credential in ``extra_headers``.
"""

import json
import tempfile
from pathlib import Path

import pytest
import yaml
from seraphim.contracts.errors import ErrorCode, SeraphimError
from seraphim.sanctum import load_config


@pytest.fixture
def temp_root():
    """A throwaway SERAPHIM root with an empty workspace config directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "config").mkdir()
        (root / ".seraphim").mkdir()
        yield root


def write_config(path: Path, domain: str, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        yaml.safe_dump(data, handle)


def _write_model(temp_root: Path, entry: dict) -> None:
    write_config(
        temp_root / ".seraphim" / "providers.yaml",
        "providers",
        {"schema_version": 1, "models": [entry]},
    )


# ---------------------------------------------------------------------------
# Defaults (a pre-S13 config keeps working unchanged)
# ---------------------------------------------------------------------------


def test_transport_defaults_are_not_materialized_by_the_loader(temp_root):
    """A pre-S13 entry still loads; transport defaults are the adapter's job.

    List entries are merged wholesale, so the loader keeps exactly the keys the
    file declares.  Defaults for the transport fields are applied by the model
    layer factory (see ``tests/model_layer/test_openai_compatible.py``), which is
    what keeps an old config working without a migration.
    """
    _write_model(temp_root, {"id": "m1", "provider": "openai", "model_name": "gpt-4o"})

    config = load_config(temp_root)
    model = config.providers.models[0]

    assert model["id"] == "m1"
    assert model.get("endpoint", "") == ""
    for key in (
        "timeout_seconds",
        "chat_path",
        "health_path",
        "auth_scheme",
        "auth_header",
        "max_tokens_field",
        "extra_headers",
        "capabilities",
    ):
        assert key not in model


def test_transport_fields_load_from_config(temp_root):
    """Every transport field is configuration-driven."""
    _write_model(
        temp_root,
        {
            "id": "local",
            "provider": "local_openai",
            "model_name": "llama3",
            "endpoint": "http://127.0.0.1:11434",
            "secret_ref": "provider.local",
            "timeout_seconds": 5.5,
            "chat_path": "/v1/chat/completions",
            "health_path": "/v1/models",
            "auth_scheme": "api_key",
            "auth_header": "api-key",
            "max_tokens_field": "max_completion_tokens",
            "extra_headers": {"X-Org": "acme"},
            "capabilities": {"tool_calls": True, "context_limit": 8192},
        },
    )

    config = load_config(temp_root)
    model = config.providers.models[0]

    assert model["endpoint"] == "http://127.0.0.1:11434"
    assert model["timeout_seconds"] == 5.5
    assert model["auth_scheme"] == "api_key"
    assert model["auth_header"] == "api-key"
    assert model["max_tokens_field"] == "max_completion_tokens"
    assert model["extra_headers"] == {"X-Org": "acme"}
    assert model["capabilities"] == {"tool_calls": True, "context_limit": 8192}


def test_streaming_fields_load_from_config(temp_root):
    """S14 streaming caps are configuration-driven too."""
    _write_model(
        temp_root,
        {
            "id": "local",
            "provider": "local_openai",
            "model_name": "llama3",
            "endpoint": "http://127.0.0.1:11434",
            "stream_max_response_bytes": 4096,
            "stream_max_event_bytes": 1024,
            "stream_max_arguments_bytes": 512,
            "stream_max_tool_calls": 4,
            "stream_idle_timeout_seconds": 1.5,
            "stream_include_usage": True,
        },
    )

    config = load_config(temp_root)
    model = config.providers.models[0]

    assert model["stream_max_response_bytes"] == 4096
    assert model["stream_max_event_bytes"] == 1024
    assert model["stream_max_arguments_bytes"] == 512
    assert model["stream_max_tool_calls"] == 4
    assert model["stream_idle_timeout_seconds"] == 1.5
    assert model["stream_include_usage"] is True


def test_streaming_fields_are_optional(temp_root):
    """A pre-S14 entry still loads; the streaming defaults are the adapter's job."""
    _write_model(temp_root, {"id": "m1", "provider": "openai", "model_name": "gpt-4o"})

    config = load_config(temp_root)
    model = config.providers.models[0]

    for key in (
        "stream_max_response_bytes",
        "stream_max_event_bytes",
        "stream_max_arguments_bytes",
        "stream_max_tool_calls",
        "stream_idle_timeout_seconds",
        "stream_include_usage",
    ):
        assert key not in model


# ---------------------------------------------------------------------------
# Credentials never live in config
# ---------------------------------------------------------------------------


def test_literal_secret_in_extra_headers_rejected(temp_root):
    """``extra_headers`` is not a place to paste an API key."""
    literal = "sk-ant-api03-abcdefghijklmnopqrstuv"
    _write_model(
        temp_root,
        {
            "id": "m1",
            "provider": "openai",
            "model_name": "gpt-4o",
            "endpoint": "https://api.example.test",
            "extra_headers": {"Authorization": literal},
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.SECRET_REF_INVALID
    assert "extra_headers.Authorization" in exc_info.value.safe_message
    # The value is never echoed back into the error.
    assert literal not in exc_info.value.safe_message
    assert literal not in json.dumps(exc_info.value.to_diagnostic_dict())


def test_unknown_key_inside_model_entry_still_rejected(temp_root):
    """Adding transport fields must not open the entry to arbitrary keys."""
    _write_model(
        temp_root,
        {
            "id": "m1",
            "provider": "openai",
            "model_name": "gpt-4o",
            "api_key": "sk-ant-api03-abcdefghijklmnopqrstuv",
        },
    )

    with pytest.raises(SeraphimError) as exc_info:
        load_config(temp_root)

    assert exc_info.value.code == ErrorCode.CONFIG_SCHEMA_INVALID
    assert "api_key" in exc_info.value.safe_message
