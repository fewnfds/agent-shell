from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)


def materialize_model_call_limit_middleware(
    block: Mapping[str, Any],
) -> ModelCallLimitMiddleware:
    return ModelCallLimitMiddleware(
        run_limit=block.get("run_limit"),
        thread_limit=block.get("thread_limit"),
        exit_behavior=block.get("exit_behavior", "end"),
    )


def materialize_tool_call_limit_middleware(
    block: Mapping[str, Any],
) -> ToolCallLimitMiddleware:
    return ToolCallLimitMiddleware(
        tool_name=block.get("tool_name"),
        run_limit=block.get("run_limit"),
        thread_limit=block.get("thread_limit"),
        exit_behavior=block.get("exit_behavior", "continue"),
    )
