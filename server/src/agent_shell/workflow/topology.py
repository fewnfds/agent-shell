from __future__ import annotations

from collections.abc import Mapping

from agent_shell.validation import ValidationIssue
from agent_shell.validation.references import reference_not_found_issue
from agent_shell.workflow.catalog import NodeHandleSpec, NodeTypeSpec, node_type_spec
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1


def _issue(
    code: str,
    path: str,
    message: str,
    message_key: str,
    *,
    owner_id: str = "",
    owner_type: str = "",
    message_args: dict[str, str | int] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        scope="workflow",
        owner_id=owner_id,
        owner_name=owner_id,
        owner_type=owner_type,
        path=path,
        message=message,
        message_key=message_key,
        message_args=message_args or {},
    )


def _edge_issue(
    edge_id: str,
    index: int,
    code: str,
    field: str,
    message: str,
    message_key: str,
    *,
    message_args: dict[str, str | int] | None = None,
) -> ValidationIssue:
    path = f"definition.edges[{index}]"
    if field:
        path += f".{field}"
    return _issue(
        code,
        path,
        message,
        message_key,
        owner_id=edge_id,
        owner_type="edge",
        message_args=message_args,
    )


def _handle(
    spec: NodeTypeSpec,
    handle_id: str,
    *,
    output: bool,
) -> NodeHandleSpec | None:
    handles = spec.output_handles if output else spec.input_handles
    return next((item for item in handles if item.id == handle_id), None)


def validate_workflow_topology(
    document: WorkflowGraphDocumentV1,
    *,
    commands: Mapping[str, object] | None = None,
) -> tuple[ValidationIssue, ...]:
    nodes = document.definition.nodes
    edges = document.definition.edges
    node_by_id = {node.id: node for node in nodes}
    specs = {
        node.id: node_type_spec(node.type, node.type_version) for node in nodes
    }
    assert all(spec is not None for spec in specs.values())

    issues: list[ValidationIssue] = []
    connections: set[tuple[str, str]] = set()
    valid_outgoing_sources: set[str] = set()

    for index, edge in enumerate(edges):
        source = node_by_id.get(edge.source)
        target = node_by_id.get(edge.target)
        if source is None:
            issues.append(
                _edge_issue(
                    edge.id,
                    index,
                    "workflow.edge_source_not_found",
                    "source",
                    "The Workflow edge source node does not exist.",
                    "validation.issue.workflow.edgeSourceNotFound",
                    message_args={"node_id": edge.source},
                )
            )
        if target is None:
            issues.append(
                _edge_issue(
                    edge.id,
                    index,
                    "workflow.edge_target_not_found",
                    "target",
                    "The Workflow edge target node does not exist.",
                    "validation.issue.workflow.edgeTargetNotFound",
                    message_args={"node_id": edge.target},
                )
            )

        source_spec = specs.get(edge.source)
        target_spec = specs.get(edge.target)
        source_handle = (
            _handle(source_spec, edge.source_handle, output=True)
            if source_spec is not None
            else None
        )
        target_handle = (
            _handle(target_spec, edge.target_handle, output=False)
            if target_spec is not None
            else None
        )
        if source is not None and source_handle is None:
            issues.append(
                _edge_issue(
                    edge.id,
                    index,
                    "workflow.edge_source_handle_invalid",
                    "source_handle",
                    "The source handle is not available on this Workflow node.",
                    "validation.issue.workflow.edgeSourceHandleInvalid",
                    message_args={"handle": edge.source_handle},
                )
            )
        if target is not None and target_handle is None:
            issues.append(
                _edge_issue(
                    edge.id,
                    index,
                    "workflow.edge_target_handle_invalid",
                    "target_handle",
                    "The target handle is not available on this Workflow node.",
                    "validation.issue.workflow.edgeTargetHandleInvalid",
                    message_args={"handle": edge.target_handle},
                )
            )
        if source_handle is not None and target_handle is not None:
            accepted = target_handle.accepted_edge_types or (target_handle.edge_type,)
            if source_handle.edge_type not in accepted:
                issues.append(
                    _edge_issue(
                        edge.id,
                        index,
                        "workflow.edge_type_mismatch",
                        "",
                        "The Workflow edge connects incompatible endpoint types.",
                        "validation.issue.workflow.edgeTypeMismatch",
                        message_args={
                            "source_type": source_handle.edge_type,
                            "target_type": target_handle.edge_type,
                        },
                    )
                )
            else:
                valid_outgoing_sources.add(edge.source)

        connection = (edge.source, edge.target)
        if connection in connections:
            issues.append(
                _edge_issue(
                    edge.id,
                    index,
                    "workflow.edge_duplicate",
                    "",
                    "A directed source and target node pair permits only one Workflow edge.",
                    "validation.issue.workflow.edgeDuplicate",
                )
            )
        else:
            connections.add(connection)

    if commands is not None:
        indexes = {node.id: index for index, node in enumerate(nodes)}
        for node in nodes:
            if node.type == "command" and node.id not in commands:
                issues.append(
                    reference_not_found_issue(
                        scope="workflow",
                        owner_id=node.id,
                        owner_name=node.id,
                        owner_type=node.type,
                        path=(
                            f"definition.nodes[{indexes[node.id]}].config.command_id"
                        ),
                        reference_id=str(node.config.get("command_id", "")),
                        expected_type="command",
                    )
                )

    node_indexes = {node.id: index for index, node in enumerate(nodes)}
    start_ids = {node.id for node in nodes if node.type == "start"}
    end_ids = {node.id for node in nodes if node.type == "end"}
    for node_type, ids in (("start", start_ids), ("end", end_ids)):
        if not ids:
            issues.append(
                _issue(
                    f"workflow.{node_type}_required",
                    "definition.nodes",
                    f"The Workflow requires at least one {node_type.title()} node.",
                    f"validation.issue.workflow.{node_type}Required",
                    owner_type="graph",
                )
            )
        elif len(ids) > 1:
            issues.append(
                _issue(
                    f"workflow.{node_type}_multiple",
                    "definition.nodes",
                    f"The Workflow requires exactly one {node_type.title()} node.",
                    f"validation.issue.workflow.{node_type}Multiple",
                    owner_type="graph",
                    message_args={"count": len(ids)},
                )
            )

    if len(start_ids) == 1:
        start_id = next(iter(start_ids))
        if start_id not in valid_outgoing_sources:
            issues.append(
                _issue(
                    "workflow.start_outgoing_required",
                    f"definition.nodes[{node_indexes[start_id]}]",
                    "The Workflow Start node requires at least one valid outgoing edge.",
                    "validation.issue.workflow.startOutgoingRequired",
                    owner_id=start_id,
                    owner_type="start",
                )
            )

    if start_ids:
        outgoing: dict[str, set[str]] = {node.id: set() for node in nodes}
        for edge in edges:
            if edge.source in node_by_id and edge.target in node_by_id:
                outgoing[edge.source].add(edge.target)
        reachable = set(start_ids)
        pending = list(start_ids)
        while pending:
            for target in outgoing[pending.pop()]:
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        for node in nodes:
            if node.type != "end" and node.id not in reachable:
                issues.append(
                    _issue(
                        "workflow.node_unreachable_from_start",
                        f"definition.nodes[{node_indexes[node.id]}]",
                        "The Workflow node is not reachable from a Start node.",
                        "validation.issue.workflow.nodeUnreachableFromStart",
                        owner_id=node.id,
                        owner_type=node.type,
                    )
                )

    return tuple(issues)


__all__ = ["validate_workflow_topology"]
