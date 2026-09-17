"""Read the flat Workflow State, publish a patch, and select a Canvas Node."""

from langgraph.types import Command


def _required_target(state, key):
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"state.{key} must be a non-empty Canvas Node ID")
    return value.strip()


def create_command():
    async def command(state, runtime):
        del runtime
        items = state.get("items")
        if not isinstance(items, list):
            raise ValueError("state.items must be a list")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("each state.items entry must be an object")

        review_count = sum(item.get("requires_review") is True for item in items)
        target = _required_target(
            state,
            "review_target_node_id" if review_count else "complete_target_node_id",
        )
        return Command(
            update={
                "item_count": len(items),
                "review_item_count": review_count,
                "selected_target_node_id": target,
            },
            goto=target,
        )

    return command
