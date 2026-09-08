from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from langgraph.runtime import ExecutionInfo, Runtime

from agent_shell import langgraph_dev
from agent_shell.runtime.agent_assistants import main_agent_assistant_id
from agent_shell.runtime.context import (
    AgentRunContext,
    AgentRuntimeContext,
    WorkflowRunContext,
    WorkflowRuntimeContext,
)
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    _AgentRunBinding,
    _RunBinding,
    _ensure_assistant,
)
from agent_shell.runtime.workflow_run_calls import WorkflowRunHandle
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.compiler import _node_runtime_context, compile_workflow


def _start_end_document():
    report, document = admit_workflow_document(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.control.v1",
                "nodes": [
                    {"id": "start", "type": "start", "type_version": 1, "config": {}},
                    {"id": "end", "type": "end", "type_version": 1, "config": {}},
                ],
                "edges": [
                    {
                        "id": "start-end",
                        "source": "start",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                    }
                ],
            },
            "layout": {
                "nodes": {},
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        }
    )
    assert report.valid
    assert document is not None
    return document


def test_factory_uses_assistant_config_and_product_run_context() -> None:
    workflow_id, configurable = langgraph_dev._factory_inputs(
        {
            "configurable": {
                "workflow_id": "workflow-1",
                "configurable_value": "kept",
            }
        }
    )
    runtime = SimpleNamespace(
        execution_runtime=SimpleNamespace(
            context={
                "request_id": "request-1",
                "lifecycle_id": "lifecycle-1",
                "caller_run_id": "caller-run-1",
                "operation_id": "operation-1",
                "workflow_id": "caller-copy-must-be-ignored",
                "run_id": "caller-copy-must-be-ignored",
            }
        )
    )

    context = langgraph_dev._execution_context(runtime, workflow_id=workflow_id)

    assert configurable["configurable_value"] == "kept"
    assert context == WorkflowRuntimeContext(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        workflow_id="workflow-1",
        caller_run_id="caller-run-1",
        operation_id="operation-1",
    )


def test_agent_factory_uses_stable_assistant_config_and_product_context() -> None:
    main_agent_id = "11111111-1111-4111-8111-111111111111"
    resolved_id, configurable = langgraph_dev._agent_factory_inputs(
        {
            "configurable": {
                "main_agent_id": main_agent_id,
                "configurable_value": "kept",
            }
        }
    )
    runtime = SimpleNamespace(
        execution_runtime=SimpleNamespace(
            context=AgentRunContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                caller_run_id="caller-1",
                operation_id="operation-1",
            )
        )
    )

    context = langgraph_dev._agent_execution_context(
        runtime,
        main_agent_id=resolved_id,
        configurable=configurable,
    )

    assert configurable["configurable_value"] == "kept"
    assert context == AgentRuntimeContext(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        main_agent_id=main_agent_id,
        caller_run_id="caller-1",
        operation_id="operation-1",
    )
    assert main_agent_assistant_id(main_agent_id) == main_agent_assistant_id(
        main_agent_id
    )
    assert main_agent_assistant_id(main_agent_id) != main_agent_id


def test_official_resource_auth_keeps_thread_reads_and_store_unmodified() -> None:
    thread_read = {"thread_id": "thread-1", "metadata": {"checkpoint_ns": ""}}
    store_access = {
        "namespace": ("workflow-lifecycle", "lifecycle-1", "runs"),
        "key": "run-1",
    }

    thread_filter = asyncio.run(
        langgraph_dev.authorize_single_owner_thread_read(None, thread_read)  # type: ignore[arg-type]
    )
    store_filter = asyncio.run(
        langgraph_dev.authorize_single_owner_store(None, store_access)  # type: ignore[arg-type]
    )

    assert thread_filter == {"owner": "agent-shell"}
    assert thread_read == {
        "thread_id": "thread-1",
        "metadata": {"checkpoint_ns": ""},
    }
    assert store_filter is None
    assert store_access == {
        "namespace": ("workflow-lifecycle", "lifecycle-1", "runs"),
        "key": "run-1",
    }


def test_agent_checkpoint_mode_selects_stateful_or_stateless_run_api() -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class Runs:
        async def create(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"run_id": "run-1", "thread_id": "thread-1"}

    owner = SimpleNamespace(run_config=lambda: {"recursion_limit": 10})
    coordinator = LifecycleRunCoordinator(
        _owner=owner,
        _snapshot=SimpleNamespace(),
        _detached_tasks=SimpleNamespace(),
    )

    async def start(checkpoint_mode: str, thread_id: str) -> None:
        binding = _AgentRunBinding(
            main_agent={
                "id": "agent-1",
                "name": "Agent",
                "durability": "exit",
                "checkpoint_mode": checkpoint_mode,
            },
            messages=[{"role": "user", "content": "hello"}],
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            public_model="Agent",
            assistant_id="assistant-1",
            thread_id=thread_id,
        )
        await coordinator._start_bound_agent_run(
            binding,
            SimpleNamespace(runs=Runs()),
        )

    asyncio.run(start("enabled", "thread-stateful"))
    asyncio.run(start("disabled", ""))

    assert calls[0][0][:2] == ("thread-stateful", "assistant-1")
    assert calls[0][1]["config"] == {"recursion_limit": 10}
    assert calls[0][1]["context"] == {
        "request_id": "request-1",
        "lifecycle_id": "lifecycle-1",
        "caller_run_id": "",
        "operation_id": "",
    }
    assert calls[0][1]["durability"] == "exit"
    assert calls[0][1]["on_completion"] is None
    assert calls[1][0][:2] == (None, "assistant-1")
    assert calls[1][1]["config"] == {"recursion_limit": 10}
    assert calls[1][1]["context"] == calls[0][1]["context"]
    assert calls[1][1]["durability"] == "exit"
    assert calls[1][1]["on_completion"] == "keep"


def test_workflow_run_creation_uses_context_without_configurable() -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class Runs:
        async def create(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"run_id": "run-1", "thread_id": "thread-1"}

    coordinator = LifecycleRunCoordinator(
        _owner=SimpleNamespace(run_config=lambda: {"recursion_limit": 10}),
        _snapshot=SimpleNamespace(),
        _detached_tasks=SimpleNamespace(),
    )
    binding = _RunBinding(
        workflow={
            "id": "workflow-1",
            "name": "Workflow",
            "durability": "async",
        },
        document=_start_end_document(),
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        public_model="Workflow",
        caller_run_id="caller-1",
        operation_id="operation-1",
        thread_id="thread-1",
        assistant_id="assistant-1",
    )

    asyncio.run(
        coordinator._start_bound_run(
            binding,
            SimpleNamespace(runs=Runs()),
        )
    )

    assert calls[0][0] == ("thread-1", "assistant-1")
    assert calls[0][1]["config"] == {"recursion_limit": 10}
    assert calls[0][1]["context"] == {
        "request_id": "request-1",
        "lifecycle_id": "lifecycle-1",
        "caller_run_id": "caller-1",
        "operation_id": "operation-1",
    }
    assert calls[0][1]["durability"] == "async"


def test_stateful_agent_opens_thread_stream_before_creating_run() -> None:
    order: list[str] = []

    class Assistants:
        async def create(self, *_args, **_kwargs):
            order.append("assistant")
            return {"assistant_id": "assistant-1", "name": "Agent"}

    class Stream:
        events = None

        async def __aenter__(self):
            order.append("stream-enter")
            return self

        async def close(self):
            order.append("stream-close")

    class Threads:
        async def create(self, *, metadata):
            assert metadata["lifecycle_id"] == "lifecycle-1"
            order.append("thread")
            return {"thread_id": "thread-1"}

        def stream(self, thread_id: str, *, assistant_id: str):
            assert (thread_id, assistant_id) == ("thread-1", "assistant-1")
            return Stream()

    class Runs:
        async def create(self, thread_id: str, assistant_id: str, **_kwargs):
            assert (thread_id, assistant_id) == ("thread-1", "assistant-1")
            order.append("run")
            return {"thread_id": thread_id, "run_id": "run-1"}

    class Client:
        assistants = Assistants()
        threads = Threads()
        runs = Runs()

        async def aclose(self):
            order.append("client-close")

    client = Client()
    owner = SimpleNamespace(
        new_agent_server_client=lambda: client,
        run_config=lambda: {"recursion_limit": 10},
        release_active_lifecycle=lambda _coordinator: None,
    )
    coordinator = LifecycleRunCoordinator(
        _owner=owner,
        _snapshot=SimpleNamespace(),
        _detached_tasks=SimpleNamespace(),
    )
    binding = _AgentRunBinding(
        main_agent={
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Agent",
            "durability": "async",
            "checkpoint_mode": "enabled",
        },
        messages=[{"role": "user", "content": "hello"}],
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        public_model="Agent",
    )

    async def scenario() -> None:
        opened_client, stream = await coordinator._open_agent_run_session(binding)
        assert opened_client is client
        assert stream is not None
        await coordinator._start_bound_agent_run(binding, opened_client)
        await coordinator.close_official_session(binding.thread_id)

    asyncio.run(scenario())
    assert order[:4] == ["assistant", "thread", "stream-enter", "run"]


def test_stable_assistant_updates_only_when_its_name_changed() -> None:
    class Assistants:
        def __init__(self, current_name: str) -> None:
            self.current_name = current_name
            self.created: list[tuple[tuple[object, ...], dict[str, object]]] = []
            self.updated: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def create(self, *args, **kwargs):
            self.created.append((args, kwargs))
            return {"assistant_id": "assistant-1", "name": self.current_name}

        async def update(self, *args, **kwargs):
            self.updated.append((args, kwargs))
            return {"assistant_id": "assistant-1", "name": kwargs["name"]}

    async def ensure(current_name: str):
        assistants = Assistants(current_name)
        result = await _ensure_assistant(
            assistants,
            "agent-shell-agent",
            assistant_id="assistant-1",
            name="Current name",
        )
        return assistants, result

    matching, matching_result = asyncio.run(ensure("Current name"))
    renamed, renamed_result = asyncio.run(ensure("Old name"))

    assert matching.created[0][1] == {
        "assistant_id": "assistant-1",
        "if_exists": "do_nothing",
        "name": "Current name",
    }
    assert matching.updated == []
    assert matching_result["name"] == "Current name"
    assert renamed.updated == [(('assistant-1',), {"name": "Current name"})]
    assert renamed_result["name"] == "Current name"


def test_windows_curl_blockbuster_compatibility_wraps_the_runtime_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langgraph_runtime_inmem import queue as inmem_queue

    calls: list[tuple[str, str]] = []

    class SocketAccept:
        def can_block_in(self, filename: str, function: str) -> None:
            calls.append((filename, function))

    blocker = SimpleNamespace(functions={"socket.socket.accept": SocketAccept()})
    monkeypatch.setattr(inmem_queue, "_enable_blockbuster", lambda: blocker)
    monkeypatch.setattr(langgraph_dev.sys, "platform", "win32")

    langgraph_dev._configure_windows_curl_blockbuster_compatibility()
    enabled = inmem_queue._enable_blockbuster
    langgraph_dev._configure_windows_curl_blockbuster_compatibility()

    assert inmem_queue._enable_blockbuster is enabled
    assert enabled() is blocker
    assert calls == [("socket.py", "_fallback_socketpair")]


def test_server_graph_context_schema_does_not_duplicate_official_identity() -> None:
    graph = compile_workflow(
        _start_end_document(),
        runtime_context=WorkflowRuntimeContext(workflow_id="workflow-1"),
    )

    assert set(graph.get_context_jsonschema()["properties"]) == {
        "request_id",
        "lifecycle_id",
        "caller_run_id",
        "operation_id",
    }


def test_server_node_binds_run_id_from_execution_info() -> None:
    class RunRuntime:
        caller = None

        async def start_workflow_run(
            self,
            target_workflow_id,
            *,
            operation_id,
            caller,
            shared_vars,
        ):
            del operation_id, shared_vars
            self.caller = caller
            return WorkflowRunHandle(
                operation_id="operation-1",
                workflow_id=target_workflow_id,
                assistant_id="assistant-1",
                thread_id="thread-2",
                run_id="run-2",
                status="pending",
            )

    run_runtime = RunRuntime()
    base = WorkflowRuntimeContext(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        workflow_id="workflow-1",
    ).with_runtime_bindings(workflow_run_runtime=run_runtime)
    runtime = Runtime(
        context=WorkflowRunContext(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
        ),
        execution_info=ExecutionInfo(
            checkpoint_id="checkpoint-1",
            checkpoint_ns="",
            task_id="task-1",
            thread_id="thread-1",
            run_id="official-run-1",
        ),
    )

    context = _node_runtime_context(runtime, base)

    assert context.run_id == "official-run-1"
    assert context.workflow_id == "workflow-1"
    assert context.lifecycle_id == "lifecycle-1"
    assert context.workflow_runs is not None
    asyncio.run(
        context.workflow_runs.start_workflow(
            "workflow-2",
            operation_id="operation-1",
        )
    )
    assert run_runtime.caller is not None
    assert run_runtime.caller.run_id == "official-run-1"


def test_server_graph_preserves_the_control_input_state() -> None:
    graph = compile_workflow(
        _start_end_document(),
        runtime_context=WorkflowRuntimeContext(workflow_id="workflow-1"),
    )

    result = graph.invoke({"shared_vars": {"request": "ready"}})

    assert result == {"shared_vars": {"request": "ready"}}
