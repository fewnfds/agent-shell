from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.messages.utils import convert_to_openai_messages
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command, Send

from agent_shell.command import (
    CommandCallable,
    CommandError,
    run_command,
)
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import WorkflowNodeInputState, WorkflowState
from agent_shell.runtime.workflow_lifecycle import lifecycle_invocations_namespace
from agent_shell.workflow.catalog import node_type_spec
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.topology import validate_workflow_topology
from agent_shell.workflow.validation import admit_workflow_document
from agent_shell.workflow_contracts import WorkflowRole


def _compile_error(code: str, message: str) -> AgentRuntimeError:
    return AgentRuntimeError(code, message, status_code=422)


def _mapping_delta(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    include_deletions: bool,
) -> dict[str, Any]:
    delta = {
        key: value
        for key, value in after.items()
        if key not in before or before[key] != value
    }
    if include_deletions:
        delta.update({key: None for key in before.keys() - after.keys()})
    return delta


def _invocation_metadata(runtime: Runtime[Any]) -> tuple[str, float]:
    execution_info = runtime.execution_info
    if (
        execution_info is None
        or not execution_info.task_id
        or execution_info.node_first_attempt_time is None
    ):
        raise AgentRuntimeError(
            "workflow.invocation_identity_unavailable",
            "The Workflow runtime did not provide the Agent invocation identity.",
            status_code=500,
        )
    return execution_info.task_id, execution_info.node_first_attempt_time


def _make_agent_node(*, node_id: str, built_agent: Any):
    async def call_agent(
        state: WorkflowNodeInputState,
        config: RunnableConfig,
        runtime: Runtime[WorkflowRuntimeContext],
    ) -> dict[str, Any]:
        invocation_id, invoked_at = _invocation_metadata(runtime)
        workflow_id = runtime.context.workflow_id
        if not workflow_id:
            raise AgentRuntimeError(
                "workflow.identity_unavailable",
                "The Workflow runtime did not provide the Workflow identity.",
                status_code=500,
            )
        if runtime.store is None:
            raise AgentRuntimeError(
                "workflow.store_unavailable",
                "The Workflow invocation artifact Store is unavailable.",
                status_code=500,
            )
        parent_shared_vars = dict(state.get("shared_vars", {}))
        parent_files = dict(state.get("files", {}))
        workflow_task = dict(state.get("workflow_task", {}))
        child_input = {
            **dict(built_agent.input_state),
            "messages": [],
            "shared_vars": parent_shared_vars,
            "files": parent_files,
        }
        if workflow_task:
            child_input["workflow_task"] = workflow_task
        child_input["workflow_state_snapshot"] = deepcopy(
            {key: value for key, value in state.items() if key != "files"}
        )
        child_context = runtime.context.for_workflow_agent(
            workflow_node_id=node_id,
            agent_id=built_agent.agent_id,
            invocation_id=invocation_id,
        )
        result = await built_agent.graph.ainvoke(
            child_input,
            config,
            context=child_context,
        )
        invocation_artifact = {
            "invocation_id": invocation_id,
            "workflow_id": workflow_id,
            "workflow_node_id": node_id,
            "agent_id": built_agent.agent_id,
            "invoked_at": invoked_at,
            "messages": convert_to_openai_messages(result["messages"]),
        }
        if workflow_task:
            invocation_artifact["workflow_task"] = deepcopy(workflow_task)
        await runtime.store.aput(
            lifecycle_invocations_namespace(
                runtime.context.lifecycle_id,
                runtime.context.workflow_run_id,
            ),
            invocation_id,
            invocation_artifact,
            index=False,
        )
        invocation_record = {
            key: invocation_artifact[key]
            for key in (
                "invocation_id",
                "workflow_id",
                "workflow_node_id",
                "agent_id",
                "invoked_at",
            )
        }
        invocation_record["result_ref"] = invocation_id
        if workflow_task:
            invocation_record["workflow_task"] = {
                key: workflow_task[key]
                for key in (
                    "command_node_id",
                    "command_invocation_id",
                    "task_id",
                    "dispatch_key",
                )
            }
        update: dict[str, Any] = {
            "agent_invocations": {invocation_id: invocation_record}
        }
        shared_vars = _mapping_delta(
            parent_shared_vars,
            result.get("shared_vars", {}),
            include_deletions=False,
        )
        if shared_vars:
            update["shared_vars"] = shared_vars
        child_files = result.get("files", parent_files)
        files = _mapping_delta(
            parent_files,
            child_files,
            include_deletions=True,
        )
        if files:
            update["files"] = files
        return update

    return call_agent


def _make_command_node(
    *,
    node_id: str,
    command: CommandCallable,
    command_targets: Mapping[str, str],
    dispatch_targets: Mapping[str, str],
):
    async def call_command(
        state: WorkflowState,
        runtime: Runtime[WorkflowRuntimeContext],
    ) -> Command:
        invocation_id, _invoked_at = _invocation_metadata(runtime)
        node_runtime = runtime.override(
            context=runtime.context.for_workflow_node(
                workflow_node_id=node_id,
                invocation_id=invocation_id,
            )
        )
        try:
            result = await run_command(
                command,
                state=state,
                runtime=node_runtime,
                allowed_branches=command_targets,
                allowed_dispatch_keys=dispatch_targets,
            )
        except CommandError as exc:
            raise AgentRuntimeError(
                "workflow.command_failed",
                "The Command Node script failed.",
                status_code=422,
            ) from exc
        parent_state = {
            key: state[key]
            for key in WorkflowState.__annotations__
            if key in state
        }
        sends = []
        for item in result.dispatch:
            workflow_task = {
                "command_node_id": node_id,
                "command_invocation_id": invocation_id,
                **item.model_dump(mode="json"),
            }
            sends.append(
                Send(
                    dispatch_targets[item.dispatch_key],
                    {**parent_state, "workflow_task": workflow_task},
                )
            )
        branch_targets = [
            command_targets[branch] for branch in result.activate
        ]
        return Command(update=result.update, goto=[*branch_targets, *sends])

    return call_command


def compile_workflow(
    document: WorkflowGraphDocumentV1,
    *,
    node_agents: Mapping[str, Any],
    commands: Mapping[str, CommandCallable] | None = None,
    workflow_role: WorkflowRole | None = None,
    checkpointer: Any | None = None,
    store: BaseStore | None = None,
) -> Any:
    """Compile catalog-declared canvas nodes into an official StateGraph."""

    admission, normalized = admit_workflow_document(
        document,
        workflow_role=workflow_role,
    )
    if normalized is None:
        issue = admission.issues[0]
        raise _compile_error(issue.code, issue.message)

    command_configs = commands or {}
    topology_issues = validate_workflow_topology(
        normalized,
        commands=command_configs,
    )
    if topology_issues:
        issue = topology_issues[0]
        raise _compile_error(issue.code, issue.message)

    nodes = normalized.definition.nodes
    entry_ids: set[str] = set()
    exit_ids: set[str] = set()
    executable_nodes = []
    for node in nodes:
        spec = node_type_spec(node.type, node.type_version)
        assert spec is not None
        if spec.runtime_kind == "graph_entry":
            entry_ids.add(node.id)
        elif spec.runtime_kind == "graph_exit":
            exit_ids.add(node.id)
        else:
            executable_nodes.append(node)

    node_by_id = {node.id: node for node in nodes}
    edge_types: dict[str, str] = {}
    branch_targets: dict[str, dict[str, str]] = {}
    dispatch_targets: dict[str, dict[str, str]] = {}
    for edge in normalized.definition.edges:
        source_node = node_by_id[edge.source]
        source_spec = node_type_spec(source_node.type, source_node.type_version)
        assert source_spec is not None
        source_handle = next(
            handle
            for handle in source_spec.output_handles
            if handle.id == edge.source_handle
        )
        edge_types[edge.id] = source_handle.edge_type
        if source_handle.edge_type == "branch":
            assert edge.branch_key is not None
            branch_targets.setdefault(edge.source, {})[edge.branch_key] = (
                END if edge.target in exit_ids else edge.target
            )
        elif source_handle.edge_type == "dispatch":
            assert edge.dispatch_key is not None
            dispatch_targets.setdefault(edge.source, {})[edge.dispatch_key] = (
                END if edge.target in exit_ids else edge.target
            )

    builder = StateGraph(WorkflowState, context_schema=WorkflowRuntimeContext)
    for node in executable_nodes:
        spec = node_type_spec(node.type, node.type_version)
        assert spec is not None
        if spec.runtime_kind == "command_node":
            command = command_configs.get(node.id)
            if command is None:
                raise _compile_error(
                    "workflow.command_not_found",
                    "The selected Command Node configuration does not exist.",
                )
            targets = branch_targets.get(node.id, {})
            dispatches = dispatch_targets.get(node.id, {})
            builder.add_node(
                node.id,
                _make_command_node(
                    node_id=node.id,
                    command=command,
                    command_targets=targets,
                    dispatch_targets=dispatches,
                ),
                destinations=tuple(
                    dict.fromkeys((*targets.values(), *dispatches.values()))
                ),
            )
            continue
        built_agent = node_agents.get(node.id)
        if built_agent is None:
            raise _compile_error(
                "workflow.node_graph_missing",
                "The Workflow node could not be materialized.",
            )
        builder.add_node(
            node.id,
            _make_agent_node(node_id=node.id, built_agent=built_agent),
            defer=bool(node.config.get("defer", False)),
        )

    # Group normal incoming edges so LangGraph receives one explicit all-of
    # waiting edge per executable target. END is a terminal sentinel, not a
    # join node: each normal source must be able to finish independently.
    incoming: dict[str, list[str]] = {}
    for edge in normalized.definition.edges:
        if edge_types[edge.id] != "normal":
            continue
        source = START if edge.source in entry_ids else edge.source
        target = END if edge.target in exit_ids else edge.target
        sources = incoming.setdefault(target, [])
        if source not in sources:
            sources.append(source)
    for target, sources in incoming.items():
        if target == END:
            for source in sources:
                builder.add_edge(source, END)
            continue
        # START independently activates the target when the graph begins. It is
        # never part of an all-of barrier; real predecessors may activate the
        # same target again later, including through a loop.
        if START in sources:
            builder.add_edge(START, target)
            sources = [source for source in sources if source != START]
        if not sources:
            continue
        builder.add_edge(sources[0] if len(sources) == 1 else sources, target)
    return builder.compile(checkpointer=checkpointer, store=store)


__all__ = ["compile_workflow"]
