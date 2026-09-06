from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command

from agent_shell.command import CommandCallable, CommandError, run_command
from agent_shell.runtime.context import WorkflowRunContext, WorkflowRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError, encode_server_run_error
from agent_shell.runtime.state import WorkflowState
from agent_shell.workflow.catalog import node_type_spec
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.topology import validate_workflow_topology
from agent_shell.workflow.validation import admit_workflow_document


def _compile_error(code: str, message: str) -> AgentRuntimeError:
    return AgentRuntimeError(code, message, status_code=422)


def _invocation_id(runtime: Runtime[Any]) -> str:
    execution_info = runtime.execution_info
    if execution_info is None or not execution_info.task_id:
        raise AgentRuntimeError(
            "workflow.invocation_identity_unavailable",
            "The Workflow runtime did not provide the Command invocation identity.",
            status_code=500,
        )
    return execution_info.task_id


def _node_runtime_context(
    runtime: Runtime[WorkflowRunContext],
    server_context: WorkflowRuntimeContext | None,
) -> WorkflowRuntimeContext:
    """Bind official Server Run identity at the Command execution boundary."""

    if server_context is None:
        context = runtime.context
        if not isinstance(context, WorkflowRuntimeContext):
            raise AgentRuntimeError(
                "workflow.context_unavailable",
                "The Workflow runtime context is unavailable.",
                status_code=500,
            )
        return context
    execution_info = runtime.execution_info
    if execution_info is None or not execution_info.run_id:
        raise AgentRuntimeError(
            "workflow.run_identity_unavailable",
            "The LangGraph Server Run identity is unavailable.",
            status_code=500,
        )
    return server_context.for_server_run(execution_info.run_id)


def _make_command_node(
    *,
    node_id: str,
    command: CommandCallable,
    target_map: Mapping[str, str],
    runtime_context: WorkflowRuntimeContext | None = None,
):
    async def call_command(
        state: WorkflowState,
        runtime: Runtime[WorkflowRuntimeContext],
    ) -> Command[Any]:
        invocation_id = _invocation_id(runtime)
        bound_context = _node_runtime_context(runtime, runtime_context)
        node_runtime = runtime.override(
            context=bound_context.for_workflow_node(
                workflow_node_id=node_id,
                node_invocation_id=invocation_id,
            )
        )
        try:
            return await run_command(
                command,
                state=state,
                runtime=node_runtime,
                target_map=target_map,
            )
        except CommandError as exc:
            error = AgentRuntimeError(
                "workflow.command_failed",
                "The Command Node script failed.",
                status_code=422,
            )
            if runtime_context is not None:
                raise RuntimeError(encode_server_run_error(error)) from exc
            raise error from exc

    return call_command


def compile_workflow(
    document: WorkflowGraphDocumentV1,
    *,
    commands: Mapping[str, CommandCallable] | None = None,
    store: BaseStore | None = None,
    runtime_context: WorkflowRuntimeContext | None = None,
) -> Any:
    """Compile a Start/Command/End control document to an official StateGraph."""

    admission, normalized = admit_workflow_document(document)
    if normalized is None:
        issue = admission.issues[0]
        raise _compile_error(issue.code, issue.message)

    command_configs = commands or {}
    topology_issues = validate_workflow_topology(normalized, commands=command_configs)
    if topology_issues:
        issue = topology_issues[0]
        raise _compile_error(issue.code, issue.message)

    entry_ids = {
        node.id for node in normalized.definition.nodes if node.type == "start"
    }
    exit_ids = {
        node.id for node in normalized.definition.nodes if node.type == "end"
    }
    command_nodes = [
        node for node in normalized.definition.nodes if node.type == "command"
    ]
    target_maps: dict[str, dict[str, str]] = {}
    for edge in normalized.definition.edges:
        if edge.source not in entry_ids:
            target_maps.setdefault(edge.source, {})[edge.target] = (
                END if edge.target in exit_ids else edge.target
            )

    builder = StateGraph(
        WorkflowState,
        context_schema=(
            WorkflowRunContext
            if runtime_context is not None
            else WorkflowRuntimeContext
        ),
    )
    for node in command_nodes:
        spec = node_type_spec(node.type, node.type_version)
        assert spec is not None and spec.runtime_kind == "command_node"
        command = command_configs.get(node.id)
        if command is None:
            raise _compile_error(
                "workflow.command_not_found",
                "The selected Command Node configuration does not exist.",
            )
        target_map = target_maps.get(node.id, {})
        builder.add_node(
            node.id,
            _make_command_node(
                node_id=node.id,
                command=command,
                target_map=target_map,
                runtime_context=runtime_context,
            ),
            destinations=tuple(dict.fromkeys(target_map.values())),
        )

    for edge in normalized.definition.edges:
        if edge.source not in entry_ids:
            continue
        target = END if edge.target in exit_ids else edge.target
        builder.add_edge(START, target)
    return builder.compile(store=store)


__all__ = ["compile_workflow"]
