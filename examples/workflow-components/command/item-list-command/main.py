"""Create one Agent dispatch task for each item in Workflow State.

This editable Command example reads ``state["shared_vars"]["items"]`` as a
non-empty list of objects such as ``{"id": "item-1", "value": 42}``. Each
item produces a stable ``item:<id>`` task ID, the ``item`` dispatch key, and a
JSON payload. Connect a Dispatch Edge named ``item`` to an Agent Node. The
target Agent receives the private ``workflow_task`` value.

The package contract is a synchronous no-argument ``create_command()`` factory
that returns an async ``command(state, runtime)`` callable. A Command result
may contain ``activate``, ``dispatch``, and ``update`` together. This package
uses only the Python standard library.
"""

from typing import Any


DISPATCH_KEY = "item"


def _task_id(item: dict[str, Any]) -> str:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("each shared_vars.items entry requires a non-empty string id")
    return f"item:{item_id.strip()}"


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        items = shared_vars.get("items") if isinstance(shared_vars, dict) else None
        if not isinstance(items, list) or not items:
            raise ValueError("shared_vars.items must be a non-empty list")
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("each shared_vars.items entry must be an object")

        tasks = [
            {
                "task_id": _task_id(item),
                "dispatch_key": DISPATCH_KEY,
                "payload": {"item": item},
            }
            for item in items
        ]
        return {
            "dispatch": tasks,
            "update": {"shared_vars": {"dispatched_count": len(tasks)}},
        }

    return command
