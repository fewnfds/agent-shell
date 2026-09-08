"""Read Workflow State, publish a shared_vars patch, and select a Canvas Node."""

from langgraph.types import Command


def _required_target(shared_vars, key):
    value = shared_vars.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"shared_vars.{key} must be a non-empty Canvas Node ID")
    return value.strip()


def create_command():
    async def command(state, runtime):
        del runtime
        shared_vars = state.get("shared_vars", {})
        if not isinstance(shared_vars, dict):
            raise ValueError("state.shared_vars must be an object")

        items = shared_vars.get("items")
        if not isinstance(items, list):
            raise ValueError("shared_vars.items must be a list")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("each shared_vars.items entry must be an object")

        review_count = sum(item.get("requires_review") is True for item in items)
        target = _required_target(
            shared_vars,
            "review_target_node_id" if review_count else "complete_target_node_id",
        )
        return Command(
            update={
                "shared_vars": {
                    "item_count": len(items),
                    "review_item_count": review_count,
                    "selected_target_node_id": target,
                }
            },
            goto=target,
        )

    return command
