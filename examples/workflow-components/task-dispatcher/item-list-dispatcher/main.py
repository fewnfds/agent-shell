"""Built-in item-list Task Dispatcher example.

This editable example reads ``state["shared_vars"]["items"]`` as a non-empty
list of objects such as ``{"id": "item-1", "value": 42}`` and creates one
task per item. Each task uses a stable ``item:<id>`` task ID, the ``item``
dispatch key, and ``{"item": item}`` as its JSON payload. The dispatcher also
writes ``shared_vars.dispatched_count``. These input fields, IDs, payload shape,
and dispatch key are example policy; change them for the Workflow and provide
matching Dispatch Edges. The target Agent consumes private ``workflow_task``
according to its own Agent Additional Prompt.

The stable package contract is a synchronous no-argument
``create_dispatcher()`` factory returning an async ``dispatch(state, runtime)``.
It may use Workflow State, ``runtime.context``, and ``runtime.store`` and must
return 1-1000 tasks with unique IDs, a valid dispatch key, and JSON-object
payloads, plus an optional State ``update``. It does not return LangGraph
``Send`` or ``Command`` objects. This package uses only the standard library,
so ``requirements.txt`` stays empty.
"""

from typing import Any


DISPATCH_KEY = "item"


def _task_id(item: dict[str, Any]) -> str:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("each shared_vars.items entry requires a non-empty string id")
    return f"item:{item_id.strip()}"


def create_dispatcher():
    async def dispatch(state, runtime):
        # Example only: tasks may be derived from any relevant Workflow State,
        # Runtime Context, or Store data. Replace this source for the Workflow.
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
            "tasks": tasks,
            # Parent-State updates are independent of each task payload.
            "update": {"shared_vars": {"dispatched_count": len(tasks)}},
        }

    return dispatch
