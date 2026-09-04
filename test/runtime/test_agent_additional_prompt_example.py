from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from langgraph.store.memory import InMemoryStore

from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.workflow_data import (
    LIFECYCLE_INPUT_KEY,
    lifecycle_input_namespace,
)


def _load_example() -> ModuleType:
    source = (
        Path(__file__).parents[2]
        / "examples"
        / "agent-components"
        / "custom-middleware"
        / "agent-additional-prompt"
        / "main.py"
    )
    spec = importlib.util.spec_from_file_location("agent_additional_prompt_example", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_additional_prompt_example_adds_private_dispatch_task() -> None:
    module = _load_example()
    middleware = module.create_middleware(
        backend=object(),
        scope="main_agent",
        package_id="example-id",
    )
    messages = [
        {"role": "system", "content": "leading"},
        {"role": "user", "content": "request"},
    ]
    context = WorkflowRuntimeContext.for_run(
        identity=WorkflowRunIdentity(
            request_id="request-id",
            lifecycle_id="lifecycle-id",
            run_id="run-id",
            workflow_id="workflow-id",
            workflow_name="Workflow",
            thread_id="thread-id",
        ),
    )
    store = InMemoryStore()
    store.put(
        lifecycle_input_namespace(context.lifecycle_id),
        LIFECYCLE_INPUT_KEY,
        {"messages": messages},
    )

    update = asyncio.run(
        middleware.abefore_agent(
            {
                "messages": [],
                "workflow_task": {
                    "task_id": "item:42",
                    "dispatch_key": "item",
                    "payload": {"id": "42"},
                },
            },
            SimpleNamespace(context=context, store=store),
        )
    )

    assert middleware.name == "AgentAdditionalPromptMiddleware_example-id"
    prepared = update["messages"].value
    assert [(message.type, message.content) for message in prepared[:2]] == [
        ("system", "leading"),
        ("human", "request"),
    ]
    assert prepared[2].type == "human"
    task = json.loads(prepared[2].content.removeprefix("Process this workflow task:\n"))
    assert task == {
        "task_id": "item:42",
        "dispatch_key": "item",
        "payload": {"id": "42"},
    }
