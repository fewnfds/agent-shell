"""Validate a list in Workflow control state and finish the current path."""

from langgraph.graph import END
from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        del runtime
        shared_vars = state.get("shared_vars", {})
        items = shared_vars.get("items") if isinstance(shared_vars, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError("shared_vars.items must be a non-empty list")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("each shared_vars.items entry must be an object")
        return Command(
            update={"shared_vars": {"item_count": len(items)}},
            goto=END,
        )

    return command
