from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any
from typing_extensions import NotRequired, TypedDict

from langgraph.channels import BaseChannel
from langgraph.errors import EmptyChannelError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import JsonValue

from agent_shell.command import (
    CommandCallable,
    CommandError,
    CommandStateSchemaError,
    run_command,
)
from agent_shell.runtime.context import WorkflowRunContext, WorkflowRuntimeContext
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext
from agent_shell.runtime.errors import AgentRuntimeError, encode_server_run_error
from agent_shell.graph_schema import GraphSchema
from agent_shell.runtime.state import (
    WORKFLOW_STATE_CHANNEL,
    WorkflowState,
    merge_workflow_state,
)
from agent_shell.workflow.catalog import node_type_spec
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.state_schema import (
    WorkflowStateSchemaError,
    compile_workflow_state_schema,
    validate_workflow_state,
)
from agent_shell.workflow.topology import validate_workflow_topology
from agent_shell.workflow.validation import admit_workflow_document


def _compile_error(code: str, message: str) -> AgentRuntimeError:
    return AgentRuntimeError(code, message, status_code=422)


class _ValidatedWorkflowStateChannel(
    BaseChannel[
        dict[str, JsonValue],
        dict[str, JsonValue],
        dict[str, JsonValue],
    ]
):
    """Validate one super-step's fully accumulated flat State atomically."""

    __slots__ = ("_has_value", "_value", "schema")

    def __init__(self, schema: GraphSchema) -> None:
        super().__init__(dict)
        self.schema = schema
        self._has_value = False
        self._value: dict[str, JsonValue] = {}

    @property
    def ValueType(self) -> type[dict[str, JsonValue]]:
        return dict

    @property
    def UpdateType(self) -> type[dict[str, JsonValue]]:
        return dict

    def copy(self) -> "_ValidatedWorkflowStateChannel":
        copied = self.__class__(self.schema)
        copied.key = self.key
        copied._has_value = self._has_value
        copied._value = self._value
        return copied

    def from_checkpoint(
        self,
        checkpoint: dict[str, JsonValue],
    ) -> "_ValidatedWorkflowStateChannel":
        restored = self.__class__(self.schema)
        restored.key = self.key
        if isinstance(checkpoint, dict):
            restored._has_value = True
            restored._value = checkpoint
        return restored

    def get(self) -> dict[str, JsonValue]:
        if not self._has_value:
            raise EmptyChannelError()
        return self._value

    def is_available(self) -> bool:
        return self._has_value

    def update(self, values: Sequence[dict[str, JsonValue]]) -> bool:
        if not values:
            return False
        merged = self._value if self._has_value else {}
        for value in values:
            merged = merge_workflow_state(merged, value)
        try:
            validate_workflow_state(merged, self.schema)
        except WorkflowStateSchemaError as exc:
            raise AgentRuntimeError(
                "workflow.state_invalid",
                str(exc),
                status_code=422,
            ) from exc
        self._has_value = True
        self._value = merged
        return True


def _workflow_graph_state_schema(schema: GraphSchema | None) -> type:
    if schema is None:
        return WorkflowState
    return TypedDict(
        "ValidatedWorkflowState",
        {
            WORKFLOW_STATE_CHANNEL: NotRequired[
                Annotated[
                    dict[str, JsonValue],
                    _ValidatedWorkflowStateChannel(schema),
                ]
            ]
        },
    )


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


def _command_failure(
    code: str,
    message: str,
    *,
    context: WorkflowRuntimeContext,
    detail_exception: BaseException,
    server_projection: bool,
) -> BaseException:
    """Persist the Command failure fact, then project only its reference."""

    diagnostics = context.diagnostics
    diagnostic_id = (
        diagnostics.runtime_error(
            detail_exception,
            code=code,
            component="graph_runtime",
            context=RuntimeDiagnosticContext(
                request_id=context.request_id,
                lifecycle_id=context.lifecycle_id,
                run_id=context.run_id,
                subject_kind="workflow",
                subject_id=context.workflow_id,
                workflow_node_id=context.workflow_node_id,
                node_invocation_id=context.node_invocation_id,
            ),
        )
        if diagnostics is not None
        else ""
    )
    error = AgentRuntimeError(
        code,
        message,
        status_code=422,
        diagnostic_id=diagnostic_id,
    )
    if server_projection:
        return RuntimeError(
            encode_server_run_error(error, detail_exception=detail_exception)
        )
    return error


def _make_command_node(
    *,
    node_id: str,
    command: CommandCallable,
    target_map: Mapping[str, str],
    runtime_context: WorkflowRuntimeContext | None = None,
    state_schema: Any | None = None,
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
                state_schema=state_schema,
            )
        except CommandStateSchemaError as exc:
            raise _command_failure(
                "workflow.state_invalid",
                str(exc),
                context=node_runtime.context,
                detail_exception=exc,
                server_projection=runtime_context is not None,
            ) from exc
        except CommandError as exc:
            raise _command_failure(
                "workflow.command_failed",
                "The Command Node script failed.",
                context=node_runtime.context,
                detail_exception=exc,
                server_projection=runtime_context is not None,
            ) from exc

    return call_command


def compile_workflow(
    document: WorkflowGraphDocumentV1,
    *,
    commands: Mapping[str, CommandCallable] | None = None,
    store: BaseStore | None = None,
    runtime_context: WorkflowRuntimeContext | None = None,
    state_schema_source: str | None = None,
) -> Any:
    """Compile a Start/Command/End control document to an official StateGraph."""

    admission, normalized = admit_workflow_document(document)
    if normalized is None:
        issue = admission.issues[0]
        raise _compile_error(issue.code, issue.message)

    command_configs = commands or {}
    state_schema = compile_workflow_state_schema(state_schema_source)
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

    graph_state_schema = _workflow_graph_state_schema(state_schema)
    builder = StateGraph(
        graph_state_schema,
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
                state_schema=state_schema,
            ),
            input_schema=graph_state_schema,
            destinations=tuple(dict.fromkeys(target_map.values())),
        )

    for edge in normalized.definition.edges:
        if edge.source not in entry_ids:
            continue
        target = END if edge.target in exit_ids else edge.target
        builder.add_edge(START, target)
    return builder.compile(store=store)


__all__ = ["compile_workflow"]
