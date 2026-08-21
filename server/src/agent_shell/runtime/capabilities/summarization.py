from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware

from agent_shell.contracts import SummarizationBlock, SummarizationThreshold


class _DisabledSummarizationMiddleware(AgentMiddleware):
    @property
    def name(self) -> str:
        return "SummarizationMiddleware"


def disabled_summarization_middleware() -> AgentMiddleware:
    """Return the same-name no-op replacement for the upstream default."""

    return _DisabledSummarizationMiddleware()


def _threshold(
    value: SummarizationThreshold,
    fallback: tuple[str, int | float],
) -> tuple[str, int | float]:
    if value.type == "auto":
        return fallback
    assert value.value is not None
    return (value.type, value.value)


def materialize_summarization_middleware(
    capability: dict[str, Any],
    *,
    model: Any,
    backend: Any,
) -> AgentMiddleware:
    """Build the explicit Deep Agents summarization override for one profile."""

    block = SummarizationBlock.model_validate(
        {key: value for key, value in capability.items() if key != "id"}
    )
    from deepagents.middleware.summarization import (
        SummarizationMiddleware,
        compute_summarization_defaults,
    )

    defaults = compute_summarization_defaults(model)
    truncate_defaults = defaults["truncate_args_settings"]
    truncate_args_settings = None
    if block.truncate_args_enabled:
        truncate_args_settings = {
            "trigger": _threshold(
                block.truncate_args_trigger,
                truncate_defaults["trigger"],
            ),
            "keep": _threshold(
                block.truncate_args_keep,
                truncate_defaults["keep"],
            ),
            "max_length": block.truncate_args_max_length,
            "truncation_text": block.truncate_args_text,
        }
    kwargs: dict[str, Any] = {
        "model": model,
        "backend": backend,
        "trigger": _threshold(block.trigger, defaults["trigger"]),
        "keep": _threshold(block.keep, defaults["keep"]),
        "trim_tokens_to_summarize": block.trim_tokens_to_summarize,
        "truncate_args_settings": truncate_args_settings,
    }
    if block.summary_prompt_override is not None:
        kwargs["summary_prompt"] = block.summary_prompt_override
    return SummarizationMiddleware(**kwargs)


__all__ = [
    "disabled_summarization_middleware",
    "materialize_summarization_middleware",
]
