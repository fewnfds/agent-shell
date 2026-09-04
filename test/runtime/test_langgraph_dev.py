from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langgraph.runtime import ExecutionInfo, Runtime

from agent_shell import langgraph_dev
from agent_shell.runtime.context import WorkflowRunContext, WorkflowRuntimeContext
from agent_shell.runtime.workflow_run_calls import WorkflowRunHandle
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.compiler import _node_runtime_context, compile_workflow


def _start_end_document():
    report, document = admit_workflow_document(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
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


def test_server_graph_context_schema_does_not_duplicate_official_identity() -> None:
    graph = compile_workflow(
        _start_end_document(),
        node_agents={},
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
            workflow_task=None,
        ):
            del operation_id, shared_vars, workflow_task
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


def test_server_graph_seeds_assembled_files_into_initial_state() -> None:
    initial_files = {"/reference.txt": {"content": ["reference"]}}
    graph = compile_workflow(
        _start_end_document(),
        node_agents={},
        runtime_context=WorkflowRuntimeContext(workflow_id="workflow-1"),
        initial_files=initial_files,
    )

    result = graph.invoke({"shared_vars": {}, "agent_invocations": {}})

    assert result["files"] == initial_files
