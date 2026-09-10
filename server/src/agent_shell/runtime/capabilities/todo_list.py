from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware


def materialize_todo_list_middleware(capability: dict[str, Any]) -> AgentMiddleware:
    """Build the configured LangChain Todo middleware for one profile."""

    from langchain.agents.middleware import TodoListMiddleware

    todo_kwargs: dict[str, str] = {}
    if capability["system_prompt_override"] is not None:
        todo_kwargs["system_prompt"] = capability["system_prompt_override"]
    if capability["tool_description_override"] is not None:
        todo_kwargs["tool_description"] = capability["tool_description_override"]
    return TodoListMiddleware(**todo_kwargs)


__all__ = [
    "materialize_todo_list_middleware",
]
