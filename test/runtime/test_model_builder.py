from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from .support import *
from .support import _build_chat_model
from langchain_core.messages import AIMessageChunk
from agent_shell.model_provider_contracts import _SETTINGS_BY_PROVIDER
from agent_shell.provider_http import provider_http_timeout
from agent_shell.provider_integrations import bundled_provider_integrations
from agent_shell.runtime import agent_builder
from agent_shell.provider_http import ProviderHttpClients
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.runtime_policy import RuntimePolicyStore


def test_model_builder_uses_the_configured_provider_timeout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}
    monkeypatch.setattr(
        agent_builder,
        "init_chat_model",
        lambda **kwargs: captured.update(kwargs) or kwargs,
    )
    policy = RuntimePolicyStore(FileConfigRepository(tmp_path / "data"))
    update = {
        key: value
        for key, value in policy.public().items()
        if key not in {"defaults", "minimums", "configurable"}
    }
    update.update(
        {
            "provider_timeout_seconds": 123,
            "provider_connect_timeout_seconds": 7,
        }
    )
    policy.update(update)

    clients = ProviderHttpClients(policy)
    _build_chat_model(
        {
            "provider": "openai",
            "model": "local",
            "base_url": "http://127.0.0.1:8000/v1",
            "provider_settings": {},
        },
        None,
        clients,
    )

    assert captured["timeout"].read == 123
    assert captured["timeout"].connect == 7
    assert captured["use_responses_api"] is False
def test_model_builder_never_reads_an_unrelated_environment_key(
    monkeypatch, provider_http_clients
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "host-secret-that-must-not-be-used")
    model = _build_chat_model(
        {
            "provider": "openai",
            "model": "local",
            "base_url": "http://127.0.0.1:8000/v1",
            "provider_settings": {},
        },
        None,
        provider_http_clients,
    )

    assert model.openai_api_key.get_secret_value() == "agent-shell-no-credential"
    assert model.use_responses_api is False


def test_model_builder_uses_the_selected_openai_connection_type(
    provider_http_clients,
) -> None:
    model = _build_chat_model(
        {
            "provider": "openai",
            "model": "gpt-5",
            "base_url": "https://api.openai.com/v1",
            "provider_settings": {"use_responses_api": True},
        },
        "provider-secret",
        provider_http_clients,
    )

    assert model.use_responses_api is True

def test_deepseek_provider_adapter_preserves_streamed_reasoning_blocks(
    provider_http_clients,
) -> None:
    model = _build_chat_model(
        {
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "base_url": "https://gateway.example.invalid/v1",
            "provider_settings": {},
        },
        "provider-secret",
        provider_http_clients,
    )

    generation = model._convert_chunk_to_generation_chunk(
        {
            "id": "response-1",
            "model": "deepseek-reasoner",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "reasoning_content": "thought"},
                    "finish_reason": None,
                }
            ],
        },
        AIMessageChunk,
        None,
    )

    assert type(model).__name__ == "ChatDeepSeek"
    assert generation is not None
    assert generation.message.content_blocks == [
        {"type": "reasoning", "reasoning": "thought"}
    ]
    assert generation.message.response_metadata["model_provider"] == "deepseek"


@pytest.mark.parametrize(
    ("provider", "settings", "credential"),
    [
        (
            "openai",
            {
                "max_completion_tokens": 100,
                "stop_sequences": ["END"],
                "reasoning_effort": "high",
                "use_responses_api": True,
            },
            "secret",
        ),
        (
            "deepseek",
            {"max_tokens": 100, "stop_sequences": ["END"], "reasoning_effort": "high"},
            "secret",
        ),
        (
            "anthropic",
            {"max_tokens_to_sample": 100, "stop": ["END"], "effort": "high"},
            "secret",
        ),
        (
            "google_genai",
            {"max_tokens": 100, "request_timeout": 4, "retries": 3, "thinking_level": "high"},
            "secret",
        ),
        (
            "google_vertexai",
            {"max_tokens": 100, "timeout": 4, "max_retries": 3},
            None,
        ),
        (
            "xai",
            {
                "max_tokens": 100,
                "stop_sequences": ["END"],
                "reasoning_effort": "high",
                "timeout": 4,
            },
            "secret",
        ),
    ],
)

def test_model_builder_passes_native_provider_fields_unchanged(
    monkeypatch,
    provider: str,
    settings: dict,
    credential: str | None,
    provider_http_clients,
) -> None:
    captured = {}

    def fake_init_chat_model(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(agent_builder, "init_chat_model", fake_init_chat_model)
    block = {
        "provider": provider,
        "model": "provider-model",
        "base_url": "https://provider.example.invalid/v1",
        "provider_settings": settings,
    }

    _build_chat_model(block, credential, provider_http_clients)

    assert captured["model"] == "provider-model"
    assert captured["model_provider"] == provider
    assert captured["base_url"] == "https://provider.example.invalid/v1"
    assert {key: captured[key] for key in settings} == settings
    if provider == "google_vertexai":
        assert "api_key" not in captured
    else:
        assert captured["api_key"].get_secret_value() == credential
    if provider in {"deepseek", "openai", "xai"}:
        assert captured["http_client"] is provider_http_clients.sync_client
        assert captured["http_async_client"] is provider_http_clients.async_client
        assert captured["default_headers"] == {"User-Agent": "Agent-Shell/0.2.0"}
        assert captured["timeout"] == settings.get("timeout", provider_http_timeout())
    else:
        assert "http_client" not in captured
        assert "http_async_client" not in captured
        assert "default_headers" not in captured

def test_provider_setting_contracts_use_current_official_constructor_names() -> None:
    for integration in bundled_provider_integrations():
        module = importlib.import_module(integration.module)
        model_type = getattr(module, integration.class_name)
        constructor_fields = inspect.signature(model_type).parameters
        contract_fields = _SETTINGS_BY_PROVIDER[integration.provider].model_fields

        assert contract_fields.keys() <= constructor_fields.keys(), integration.provider

def test_model_builder_requires_vertex_application_default_credentials(
    monkeypatch, provider_http_clients
) -> None:
    monkeypatch.setattr(agent_builder, "init_chat_model", lambda **kwargs: kwargs)

    with pytest.raises(AgentRuntimeError) as vertex_credential:
        _build_chat_model(
            {
                "provider": "google_vertexai",
                "model": "gemini",
                "base_url": "https://aiplatform.googleapis.com",
                "provider_settings": {},
            },
            "api-key-is-not-google-credentials",
            provider_http_clients,
        )

    assert vertex_credential.value.code == "model_configuration_invalid"
