"""Agent Additional Prompt (AAP) Middleware example.

The suggested policy gives a Main Agent the current Lifecycle request messages,
keeps a Subagent's privately delegated messages, and appends a Task Dispatcher
worker's ``workflow_task`` as a user message. Customize
``build_agent_additional_prompt_messages`` to select, trim, reorder, or extend
that Agent's private initial messages.

For upstream results, select records by explicit node or task identity from
``state["workflow_state_snapshot"]["agent_invocations"]`` and pass the chosen
record to ``load_invocation_artifact``. Do not depend on insertion order or
automatically copy every upstream Agent's full output.

The standard-library and Agent Shell/LangChain imports below need no package
entry in requirements.txt. Add only direct third-party dependencies there and
restart Agent Shell to prepare them. This is trusted server-side Python code;
it does not run in a sandbox.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages.utils import convert_to_messages, convert_to_openai_messages
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from agent_shell.middleware_packages.messages import mutable_request_messages
from agent_shell.runtime.workflow_lifecycle import (
    LIFECYCLE_INPUT_KEY,
    lifecycle_input_namespace,
    lifecycle_invocations_namespace,
)


async def load_invocation_artifact(
    runtime: Runtime[Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Load one explicitly selected upstream Agent result."""

    result_ref = record.get("result_ref")
    context = runtime.context
    if runtime.store is None or not isinstance(result_ref, str) or not result_ref:
        raise RuntimeError("workflow invocation artifact is unavailable")
    item = await runtime.store.aget(
        lifecycle_invocations_namespace(context.lifecycle_id, context.run_id),
        result_ref,
    )
    value = getattr(item, "value", None)
    if not isinstance(value, dict):
        raise RuntimeError("workflow invocation artifact is unavailable")
    return deepcopy(value)


async def build_agent_additional_prompt_messages(
    state: dict[str, Any],
    runtime: Runtime[Any],
    request_messages: list[dict[str, Any]],
    backend: Any,
) -> list[dict[str, Any]]:
    """Build the private initial messages for one Agent invocation."""

    messages = mutable_request_messages(request_messages)

    # Suggested default: expose a Task Dispatcher worker's private task.
    # Remove or transform this block when the Agent needs a different context.
    task = state.get("workflow_task")
    if isinstance(task, dict):
        messages.append(
            {
                "role": "user",
                "content": "Process this workflow task:\n"
                + json.dumps(
                    {
                        "task_id": task.get("task_id"),
                        "dispatch_key": task.get("dispatch_key"),
                        "payload": task.get("payload", {}),
                    },
                    ensure_ascii=False,
                ),
            }
        )

    # Add Workflow-specific selection, trimming, file reads, or upstream-result
    # loading here. The Workflow filesystem backend is available as `backend`.
    # Select an invocation record from state["workflow_state_snapshot"] first,
    # then call load_invocation_artifact(runtime, record) when full output is needed.
    return messages


async def _initial_prompt_messages(
    state: dict[str, Any],
    runtime: Runtime[Any],
    *,
    scope: str,
    backend: Any,
) -> list[dict[str, Any]]:
    if scope == "subagent":
        # A Subagent keeps the private messages delegated by its parent Agent.
        return mutable_request_messages(
            convert_to_openai_messages(state.get("messages", []))
        )

    context = runtime.context
    if runtime.store is None or not context.lifecycle_id:
        raise RuntimeError("workflow lifecycle input is unavailable")
    item = await runtime.store.aget(
        lifecycle_input_namespace(context.lifecycle_id),
        LIFECYCLE_INPUT_KEY,
    )
    value = getattr(item, "value", None)
    request_messages = value.get("messages") if isinstance(value, dict) else None
    if not isinstance(request_messages, list):
        raise RuntimeError("workflow lifecycle input is unavailable")
    return await build_agent_additional_prompt_messages(
        state,
        runtime,
        request_messages,
        backend,
    )


class AgentAdditionalPromptMiddleware(AgentMiddleware):
    def __init__(self, *, backend: Any, scope: str, package_id: str) -> None:
        super().__init__()
        self._backend = backend
        self._scope = scope
        self._name = f"AgentAdditionalPromptMiddleware_{package_id}"

    @property
    def name(self) -> str:
        return self._name

    async def abefore_agent(
        self,
        state: dict[str, Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any]:
        messages = await _initial_prompt_messages(
            state,
            runtime,
            scope=self._scope,
            backend=self._backend,
        )
        return {"messages": Overwrite(convert_to_messages(messages))}


def create_middleware(
    backend: Any,
    scope: str,
    package_id: str,
    **_available: Any,
) -> AgentMiddleware:
    return AgentAdditionalPromptMiddleware(
        backend=backend,
        scope=scope,
        package_id=package_id,
    )
