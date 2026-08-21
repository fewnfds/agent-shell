from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import ValidationError

from agent_shell.validation import (
    ValidationIssue,
    ValidationReport,
    report_from_validation_error,
)
from agent_shell.workflow.catalog import node_type_spec, supported_node_versions
from agent_shell.workflow.contracts import (
    WorkflowGraphDocumentV1,
    WorkflowNodeV1,
)
from agent_shell.workflow.topology import validate_workflow_topology
from agent_shell.workflow_contracts import WorkflowRole


WORKFLOW_ADMISSION_STAGE = "workflow_draft"
WORKFLOW_EXECUTABLE_STAGE = "workflow_publish"

MainAgentValidator = Callable[[str], ValidationReport]
MessageArgs = dict[str, str | int | float | bool | None]


def _issue(
    *,
    code: str,
    path: str,
    message: str,
    message_key: str,
    owner_id: str = "",
    owner_type: str = "",
    message_args: MessageArgs | None = None,
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


def _node_issue(
    node: WorkflowNodeV1,
    index: int,
    *,
    code: str,
    field: str,
    message: str,
    message_key: str,
    message_args: MessageArgs | None = None,
) -> ValidationIssue:
    path = f"definition.nodes[{index}]"
    if field:
        path += f".{field}"
    return _issue(
        code=code,
        path=path,
        message=message,
        message_key=message_key,
        owner_id=node.id,
        owner_type=node.type,
        message_args=message_args,
    )


def _config_issues(
    node: WorkflowNodeV1,
    index: int,
    exc: ValidationError,
) -> list[ValidationIssue]:
    report = report_from_validation_error(
        exc,
        stage=WORKFLOW_ADMISSION_STAGE,
        scope="workflow",
        owner_id=node.id,
        owner_name=node.id,
        owner_type=node.type,
    )
    result = []
    for issue in report.issues:
        suffix = f".{issue.path}" if issue.path else ""
        result.append(
            ValidationIssue(
                code=issue.code,
                scope="workflow",
                owner_id=node.id,
                owner_name=node.id,
                owner_type=node.type,
                path=f"definition.nodes[{index}].config{suffix}",
                message=issue.message,
                message_key=issue.message_key,
                message_args=issue.message_args,
                severity=issue.severity,
            )
        )
    return result


def _normalize_nodes(
    document: WorkflowGraphDocumentV1,
    issues: list[ValidationIssue],
    *,
    workflow_role: WorkflowRole | None,
) -> list[WorkflowNodeV1]:
    indexes: dict[str, int] = {}
    normalized = []
    for index, node in enumerate(document.definition.nodes):
        previous = indexes.get(node.id)
        if previous is not None:
            issues.append(
                _node_issue(
                    node,
                    index,
                    code="workflow.node_id_duplicate",
                    field="id",
                    message="Workflow node IDs must be unique.",
                    message_key="validation.issue.workflow.nodeIdDuplicate",
                    message_args={"first_index": previous},
                )
            )
        else:
            indexes[node.id] = index

        spec = node_type_spec(node.type, node.type_version)
        if spec is None:
            versions = supported_node_versions(node.type)
            code = (
                "workflow.node_type_unsupported"
                if versions is None
                else "workflow.node_version_unsupported"
            )
            field = "type" if versions is None else "type_version"
            message = (
                "The Workflow node type is not supported."
                if versions is None
                else "The Workflow node type version is not supported."
            )
            args: MessageArgs = {"type": node.type}
            if versions is not None:
                args["version"] = node.type_version
            issues.append(
                _node_issue(
                    node,
                    index,
                    code=code,
                    field=field,
                    message=message,
                    message_key=(
                        "validation.issue.workflow.nodeTypeUnsupported"
                        if versions is None
                        else "validation.issue.workflow.nodeVersionUnsupported"
                    ),
                    message_args=args,
                )
            )
            normalized.append(node)
            continue

        try:
            config = spec.config_model.model_validate(node.config).model_dump(mode="json")
        except ValidationError as exc:
            issues.extend(_config_issues(node, index, exc))
            normalized.append(node)
        else:
            normalized.append(node.model_copy(update={"config": config}))
        if workflow_role is not None and workflow_role not in spec.workflow_roles:
            issues.append(
                _node_issue(
                    node,
                    index,
                    code="workflow.node_role_not_allowed",
                    field="type",
                    message="The Workflow node type is not available for this Workflow role.",
                    message_key="validation.issue.workflow.nodeRoleNotAllowed",
                    message_args={"workflow_role": workflow_role},
                )
            )
    return normalized


def _admission_issues(
    document: WorkflowGraphDocumentV1,
    *,
    workflow_role: WorkflowRole | None,
) -> tuple[list[ValidationIssue], WorkflowGraphDocumentV1]:
    issues: list[ValidationIssue] = []
    nodes = _normalize_nodes(document, issues, workflow_role=workflow_role)
    normalized = document.model_copy(
        update={
            "definition": document.definition.model_copy(update={"nodes": nodes})
        }
    )

    edge_indexes: dict[str, int] = {}
    for index, edge in enumerate(normalized.definition.edges):
        previous = edge_indexes.get(edge.id)
        if previous is not None:
            issues.append(
                _issue(
                    code="workflow.edge_id_duplicate",
                    path=f"definition.edges[{index}].id",
                    message="Workflow edge IDs must be unique.",
                    message_key="validation.issue.workflow.edgeIdDuplicate",
                    owner_id=edge.id,
                    owner_type="edge",
                    message_args={"first_index": previous},
                )
            )
        else:
            edge_indexes[edge.id] = index

    node_ids = {node.id for node in normalized.definition.nodes}
    for node_id in normalized.layout.nodes:
        if node_id not in node_ids:
            issues.append(
                _issue(
                    code="workflow.layout_node_not_found",
                    path=f"layout.nodes.{node_id}",
                    message="The Workflow layout references a node that does not exist.",
                    message_key="validation.issue.workflow.layoutNodeNotFound",
                    owner_id=node_id,
                    owner_type="layout",
                )
            )

    return issues, normalized


def admit_workflow_document(
    payload: object,
    *,
    workflow_role: WorkflowRole | None = None,
) -> tuple[ValidationReport, WorkflowGraphDocumentV1 | None]:
    try:
        document = WorkflowGraphDocumentV1.model_validate(payload)
    except ValidationError as exc:
        return (
            report_from_validation_error(
                exc,
                stage=WORKFLOW_ADMISSION_STAGE,
                scope="workflow",
                owner_type="graph",
            ),
            None,
        )

    issues, normalized = _admission_issues(
        document,
        workflow_role=workflow_role,
    )
    report = ValidationReport(stage=WORKFLOW_ADMISSION_STAGE, issues=tuple(issues))
    return report, normalized if report.valid else None


def validate_workflow_executable(
    document: WorkflowGraphDocumentV1,
    *,
    validate_main_agent: MainAgentValidator,
    commands: Mapping[str, object] | None = None,
    task_dispatchers: Mapping[str, object] | None = None,
    workflow_role: WorkflowRole | None = None,
) -> ValidationReport:
    admission, normalized = admit_workflow_document(
        document,
        workflow_role=workflow_role,
    )
    if normalized is None:
        return ValidationReport(
            stage=WORKFLOW_EXECUTABLE_STAGE,
            issues=admission.issues,
        )

    issues = list(
        validate_workflow_topology(
            normalized,
            commands=commands,
            task_dispatchers=task_dispatchers,
        )
    )
    node_index = {
        node.id: index for index, node in enumerate(normalized.definition.nodes)
    }
    agent_reports: dict[str, ValidationReport] = {}
    for node in normalized.definition.nodes:
        if node.type != "agent":
            continue
        main_agent_id = str(node.config["main_agent_id"])
        report = agent_reports.get(main_agent_id)
        if report is None:
            report = validate_main_agent(main_agent_id)
            agent_reports[main_agent_id] = report
        for referenced in report.issues:
            issues.append(
                ValidationIssue(
                    code=referenced.code,
                    scope="workflow",
                    owner_id=node.id,
                    owner_name=node.id,
                    owner_type="agent",
                    path=(
                        f"definition.nodes[{node_index[node.id]}].config.main_agent_id"
                    ),
                    message=referenced.message,
                    message_key=referenced.message_key,
                    message_args=referenced.message_args,
                    severity=referenced.severity,
                )
            )

    return ValidationReport(stage=WORKFLOW_EXECUTABLE_STAGE, issues=tuple(issues))


__all__ = [
    "MainAgentValidator",
    "WORKFLOW_ADMISSION_STAGE",
    "WORKFLOW_EXECUTABLE_STAGE",
    "admit_workflow_document",
    "validate_workflow_executable",
]
