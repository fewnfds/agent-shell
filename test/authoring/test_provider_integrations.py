from __future__ import annotations

from pathlib import Path

from agent_shell.provider_integrations import bundled_provider_integrations

from .app_support import make_client


def test_catalog_exposes_release_managed_provider_integrations(
    tmp_path: Path, monkeypatch
) -> None:
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/api/model-providers")

    assert response.status_code == 200, response.text
    providers = {item["provider"]: item for item in response.json()["providers"]}
    assert set(providers) == {
        "openai",
        "anthropic",
        "google_vertexai",
        "google_genai",
        "deepseek",
        "xai",
    }
    assert all(item["installed"] for item in providers.values())
    assert all(item["version"] for item in providers.values())


def test_bundled_provider_set_is_owned_by_the_release() -> None:
    integrations = {item.provider: item for item in bundled_provider_integrations()}

    assert integrations["openai"].package == "langchain-openai"
    assert integrations["openai"].module == "langchain_openai"
    assert integrations["openai"].class_name == "ChatOpenAI"
    assert integrations["deepseek"].package == "langchain-deepseek"
    assert integrations["xai"].package == "langchain-xai"
