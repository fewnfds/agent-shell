from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware

from agent_shell.contracts import PromptCachingBlock


class _DisabledAnthropicPromptCachingMiddleware(AgentMiddleware):
    @property
    def name(self) -> str:
        return "AnthropicPromptCachingMiddleware"


def disabled_prompt_caching_middleware() -> AgentMiddleware:
    """Return the same-name no-op replacement for the upstream default."""

    return _DisabledAnthropicPromptCachingMiddleware()


def materialize_prompt_caching_middleware(
    capability: dict[str, Any],
) -> AgentMiddleware:
    """Build the explicit Anthropic prompt-caching override for one profile."""

    block = PromptCachingBlock.model_validate(
        {key: value for key, value in capability.items() if key != "id"}
    )

    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    return AnthropicPromptCachingMiddleware(
        type=block.type,
        ttl=block.ttl,
        min_messages_to_cache=block.min_messages_to_cache,
        unsupported_model_behavior="ignore",
    )


__all__ = [
    "disabled_prompt_caching_middleware",
    "materialize_prompt_caching_middleware",
]
