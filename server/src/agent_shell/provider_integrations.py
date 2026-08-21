from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass

_PACKAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True, slots=True)
class ProviderIntegration:
    provider: str
    package: str
    module: str
    class_name: str


_BUNDLED_PROVIDER_INTEGRATIONS = (
    ProviderIntegration(
        provider="anthropic",
        package="langchain-anthropic",
        module="langchain_anthropic",
        class_name="ChatAnthropic",
    ),
    ProviderIntegration(
        provider="deepseek",
        package="langchain-deepseek",
        module="langchain_deepseek",
        class_name="ChatDeepSeek",
    ),
    ProviderIntegration(
        provider="google_genai",
        package="langchain-google-genai",
        module="langchain_google_genai",
        class_name="ChatGoogleGenerativeAI",
    ),
    ProviderIntegration(
        provider="google_vertexai",
        package="langchain-google-vertexai",
        module="langchain_google_vertexai",
        class_name="ChatVertexAI",
    ),
    ProviderIntegration(
        provider="openai",
        package="langchain-openai",
        module="langchain_openai",
        class_name="ChatOpenAI",
    ),
    ProviderIntegration(
        provider="xai",
        package="langchain-xai",
        module="langchain_xai",
        class_name="ChatXAI",
    ),
)


def bundled_provider_integrations() -> tuple[ProviderIntegration, ...]:
    """Return the exact Provider integrations shipped by this release."""
    return _BUNDLED_PROVIDER_INTEGRATIONS


def bundled_provider_ids() -> frozenset[str]:
    return frozenset(item.provider for item in bundled_provider_integrations())


def _distribution_snapshot() -> dict[str, str]:
    installed = {}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").lower()
        if name and _PACKAGE_RE.fullmatch(name):
            installed[name] = distribution.version
    return installed


def provider_catalog() -> dict[str, object]:
    installed = _distribution_snapshot()
    providers = []
    for integration in bundled_provider_integrations():
        version = installed.get(integration.package.lower())
        providers.append(
            {
                "provider": integration.provider,
                "package": integration.package,
                "class_name": integration.class_name,
                "installed": version is not None,
                "version": version,
                "documentation_url": (
                    "https://docs.langchain.com/oss/python/integrations/providers/overview"
                ),
            }
        )
    return {
        "langchain_version": installed.get("langchain", ""),
        "providers": providers,
    }
