from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Annotated, Any, get_type_hints
from typing_extensions import NotRequired, TypedDict

from langgraph.channels import BaseChannel
from langgraph.errors import EmptyChannelError
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import BaseModel

from agent_shell.command import normalize_command_goto
from agent_shell.graph_schema import GraphSchema, GraphSchemaError
from agent_shell.runtime.context import McpToolRuntimeContext
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.state import merge_workflow_state
from agent_shell.workflow.catalog import node_type_spec
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.topology import validate_workflow_topology
from agent_shell.workflow.validation import admit_workflow_document


_MCP_TOOL_STATE_CHANNEL = "__agent_shell_mcp_tool_state__"
_MCP_TOOL_INPUT_NODE = "__agent_shell_mcp_tool_input__"
_MCP_TOOL_OUTPUT_NODE = "__agent_shell_mcp_tool_output__"


def _compile_error(code: str, message: str) -> AgentRuntimeError:
    return AgentRuntimeError(code, message, status_code=422)


class _ValidatedMcpToolStateChannel(
    BaseChannel[dict[str, Any], dict[str, Any], dict[str, Any]]
):
    """Merge and validate one complete MCP Tool State super-step."""

    __slots__ = ("_has_value", "_value", "schema")

    def __init__(self, schema: GraphSchema) -> None:
        super().__init__(dict)
        self.schema = schema
        self._has_value = False
        self._value: dict[str, Any] = {}

    @property
    def ValueType(self) -> type[dict[str, Any]]:
        return dict

    @property
    def UpdateType(self) -> type[dict[str, Any]]:
        return dict

    def copy(self) -> "_ValidatedMcpToolStateChannel":
        copied = self.__class__(self.schema)
        copied.key = self.key
        copied._has_value = self._has_value
        copied._value = self._value
        return copied

    def from_checkpoint(
        self,
        checkpoint: dict[str, Any],
    ) -> "_ValidatedMcpToolStateChannel":
        restored = self.__class__(self.schema)
        restored.key = self.key
        if isinstance(checkpoint, dict):
            restored._has_value = True
            restored._value = checkpoint
        return restored

    def get(self) -> dict[str, Any]:
        if not self._has_value:
            raise EmptyChannelError()
        return self._value

    def is_available(self) -> bool:
        return self._has_value

    def update(self, values: Sequence[dict[str, Any]]) -> bool:
        if not values:
            return False
        merged = self._value if self._has_value else {}
        for value in values:
            merged = merge_workflow_state(merged, value)
        try:
            self.schema.validate_state(merged)
        except GraphSchemaError as exc:
            raise AgentRuntimeError(
                "mcp_tool.state_invalid",
                str(exc),
                status_code=422,
            ) from exc
        self._has_value = True
        self._value = merged
        return True


def _mcp_tool_graph_state_schema(schema: GraphSchema) -> type:
    return TypedDict(
        "ValidatedMcpToolState",
        {
            **get_type_hints(schema.state_model, include_extras=True),
            _MCP_TOOL_STATE_CHANNEL: NotRequired[
                Annotated[
                    dict[str, Any],
                    _ValidatedMcpToolStateChannel(schema),
                ]
            ],
        },
        total=False,
    )


def _flat_state(state: Any, *, schema: GraphSchema | None) -> dict[str, Any]:
    if isinstance(state, BaseModel):
        return state.model_dump(mode="python")
    if isinstance(state, Mapping):
        if schema is not None:
            stored = state.get(_MCP_TOOL_STATE_CHANNEL)
            if isinstance(stored, Mapping):
                return dict(stored)
        return dict(state)
    raise TypeError("MCP Tool state must be a mapping or Pydantic model")


def _schema_graph_update(
    update: Mapping[str, Any],
    schema: GraphSchema,
) -> dict[str, Any]:
    public_fields = schema.state_model.model_fields
    return {
        **{key: value for key, value in update.items() if key in public_fields},
        _MCP_TOOL_STATE_CHANNEL: dict(update),
    }


def _make_schema_input_node(schema: GraphSchema):
    def initialize_state(state: Any) -> dict[str, Any]:
        return _schema_graph_update(_flat_state(state, schema=schema), schema)

    return initialize_state


def _make_schema_output_node(schema: GraphSchema):
    def validate_output(state: Any) -> None:
        try:
            schema.validate_output(_flat_state(state, schema=schema))
        except GraphSchemaError as exc:
            raise AgentRuntimeError(
                "mcp_tool.output_invalid",
                str(exc),
                status_code=422,
            ) from exc

    return validate_output


def _invocation_id(runtime: Runtime[McpToolRuntimeContext]) -> str:
    execution_info = runtime.execution_info
    if execution_info is None or not execution_info.task_id:
        raise AgentRuntimeError(
            "mcp_tool.invocation_identity_unavailable",
            "The MCP Tool runtime did not provide the Command invocation identity.",
            status_code=500,
        )
    return execution_info.task_id


def _make_command_node(
    *,
    mcp_tool_id: str,
    node_id: str,
    command: Any,
    target_map: Mapping[str, str],
    schema: GraphSchema | None,
    mcp_commands_by_node: Mapping[str, Any] | None,
):
    async def call_command(
        state: Any,
        runtime: Runtime[McpToolRuntimeContext],
    ) -> Command[Any]:
        invocation_id = _invocation_id(runtime)
        execution_info = runtime.execution_info
        run_id = execution_info.run_id if execution_info is not None else ""
        context = McpToolRuntimeContext(
            mcp_tool_id=mcp_tool_id,
            run_id=run_id,
            _mcp_commands_by_node=mcp_commands_by_node,
        )
        node_runtime = runtime.override(
            context=context.for_mcp_tool_node(
                node_id=node_id,
                invocation_id=invocation_id,
            )
        )
        flat_state = _flat_state(state, schema=schema)
        try:
            result = await command(
                state=deepcopy(flat_state),
                runtime=node_runtime,
            )
            if not isinstance(result, Command):
                raise TypeError("command must return langgraph.types.Command")
            if result.graph is not None:
                raise ValueError("command graph routing is not supported")
            if result.resume is not None:
                raise ValueError("command resume is not supported")
            raw_update = result.update
            if raw_update is None:
                update: dict[str, Any] = {}
            elif isinstance(raw_update, Mapping):
                update = deepcopy(dict(raw_update))
            else:
                raise TypeError("command update must be a mapping")
            if schema is not None:
                schema.validate_state({**flat_state, **update})
                graph_update = _schema_graph_update(update, schema)
            else:
                graph_update = {"__root__": update} if update else None
            return Command(
                update=graph_update or None,
                goto=normalize_command_goto(result.goto, target_map),
            )
        except GraphSchemaError as exc:
            raise AgentRuntimeError(
                "mcp_tool.state_invalid",
                str(exc),
                status_code=422,
            ) from exc
        except AgentRuntimeError:
            raise
        except Exception as exc:
            raise AgentRuntimeError(
                "mcp_tool.command_failed",
                "The MCP Tool Command Node script failed.",
                status_code=422,
                source_exception_type=type(exc).__name__,
            ) from exc

    return call_command


def compile_mcp_tool_graph(
    document: WorkflowGraphDocumentV1,
    *,
    mcp_tool_id: str,
    commands: Mapping[str, Any] | None = None,
    schema: GraphSchema | None = None,
    mcp_commands_by_node: Mapping[str, Any] | None = None,
    store: BaseStore | None = None,
) -> Any:
    """Compile one independent MCP Tool Graph for an official /mcp Run."""

    admission, normalized = admit_workflow_document(document)
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
    end_target = _MCP_TOOL_OUTPUT_NODE if schema is not None else END
    for edge in normalized.definition.edges:
        if edge.source not in entry_ids:
            target_map = target_maps.setdefault(edge.source, {})
            target_map[edge.target] = (
                end_target if edge.target in exit_ids else edge.target
            )
            if edge.target in exit_ids:
                target_map[END] = end_target

    open_state_schema = Annotated[dict[str, Any], merge_workflow_state]
    state_schema = (
        _mcp_tool_graph_state_schema(schema)
        if schema is not None
        else open_state_schema
    )
    input_schema = (
        schema.input_model
        if schema is not None and schema.input_model is not None
        else state_schema
    )
    output_schema = (
        schema.output_model
        if schema is not None and schema.output_model is not None
        else state_schema
    )
    builder = StateGraph(
        state_schema,
        input_schema=input_schema,
        output_schema=output_schema,
        context_schema=McpToolRuntimeContext,
    )
    if schema is not None:
        builder.add_node(
            _MCP_TOOL_INPUT_NODE,
            _make_schema_input_node(schema),
            input_schema=schema.state_model,
        )
        builder.add_node(
            _MCP_TOOL_OUTPUT_NODE,
            _make_schema_output_node(schema),
            defer=True,
        )
        builder.add_edge(_MCP_TOOL_OUTPUT_NODE, END)
    for node in command_nodes:
        spec = node_type_spec(node.type, node.type_version)
        assert spec is not None and spec.runtime_kind == "command_node"
        command = command_configs.get(node.id)
        if command is None:
            raise _compile_error(
                "mcp_tool.command_not_found",
                "The selected MCP Tool Command Node configuration does not exist.",
            )
        target_map = target_maps.get(node.id, {})
        builder.add_node(
            node.id,
            _make_command_node(
                mcp_tool_id=mcp_tool_id,
                node_id=node.id,
                command=command,
                target_map=target_map,
                schema=schema,
                mcp_commands_by_node=mcp_commands_by_node,
            ),
            destinations=tuple(dict.fromkeys(target_map.values())),
        )

    if schema is not None:
        builder.add_edge(START, _MCP_TOOL_INPUT_NODE)
    for edge in normalized.definition.edges:
        if edge.source not in entry_ids:
            continue
        target = end_target if edge.target in exit_ids else edge.target
        builder.add_edge(
            _MCP_TOOL_INPUT_NODE if schema is not None else START,
            target,
        )
    return builder.compile(store=store)


__all__ = ["compile_mcp_tool_graph"]
