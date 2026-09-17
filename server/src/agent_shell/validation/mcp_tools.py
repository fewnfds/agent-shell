from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from pydantic import Field, ValidationError

from agent_shell.mcp_tool_contracts import McpToolDefinition
from agent_shell.storage.blocks import BlockStore
from agent_shell.validation.contracts import report_from_validation_error
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.validation.workflows import (
    WorkflowConfigurationValidator,
    workflow_executable_report,
)
from agent_shell.workflow.catalog import CommandNodeConfig
from agent_shell.workflow.contracts import (
    WorkflowGraphDefinitionV1,
    WorkflowGraphDocumentV1,
    WorkflowLayoutV1,
)
from agent_shell.workflow.validation import (
    WORKFLOW_EXECUTABLE_STAGE,
    admit_workflow_document,
)


class StoredMcpToolConfiguration(McpToolDefinition):
    enabled: Annotated[bool, Field(strict=True)]
    definition: WorkflowGraphDefinitionV1
    layout: WorkflowLayoutV1


def _mcp_tool_issue(issue: ValidationIssue, *, owner_id: str, owner_name: str) -> ValidationIssue:
    code = issue.code
    if code.startswith("workflow."):
        code = f"mcp_tool.{code.removeprefix('workflow.')}"
    return replace(
        issue,
        code=code,
        scope="mcp_tool",
        owner_id=issue.owner_id or owner_id,
        owner_name=issue.owner_name or owner_name,
    )


def _lifecycle_dependency_issues(
    document: WorkflowGraphDocumentV1,
    *,
    owner_id: str,
    owner_name: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for index, node in enumerate(document.definition.nodes):
        if node.type != "command":
            continue
        config = CommandNodeConfig.model_validate(node.config)
        if config.external_agent_id is None:
            continue
        issues.append(
            ValidationIssue(
                code="mcp_tool.lifecycle_dependency",
                scope="mcp_tool",
                owner_id=node.id,
                owner_name=node.id,
                owner_type=node.type,
                path=(
                    f"definition.nodes[{index}].config.external_agent_id"
                ),
                message=(
                    "MCP Tool Command nodes cannot depend on External Agents "
                    "or Lifecycle-scoped execution."
                ),
                message_key="validation.issue.mcpTool.lifecycleDependency",
                message_args={},
            )
        )
    return issues


def mcp_tool_executable_report(
    document: WorkflowGraphDocumentV1,
    *,
    mcp_tool: dict[str, Any],
    blocks: BlockStore,
    configuration_validation: WorkflowConfigurationValidator,
    include_draft_admission: bool = False,
) -> ValidationReport:
    owner_id = str(mcp_tool.get("id", ""))
    owner_name = str(mcp_tool.get("name", ""))
    issues: list[ValidationIssue] = []
    normalized = document
    if include_draft_admission:
        admission, admitted = admit_workflow_document(document)
        issues.extend(
            _mcp_tool_issue(issue, owner_id=owner_id, owner_name=owner_name)
            for issue in admission.issues
        )
        if admitted is None:
            return ValidationReport(
                stage=WORKFLOW_EXECUTABLE_STAGE,
                issues=tuple(issues),
            )
        normalized = admitted

    issues.extend(
        _lifecycle_dependency_issues(
            normalized,
            owner_id=owner_id,
            owner_name=owner_name,
        )
    )
    executable = workflow_executable_report(
        normalized,
        workflow={
            "id": owner_id,
            "name": owner_name or "mcp-tool",
            "workflow_event_output_id": None,
        },
        blocks=blocks,
        configuration_validation=configuration_validation,
    )
    issues.extend(
        _mcp_tool_issue(issue, owner_id=owner_id, owner_name=owner_name)
        for issue in executable.issues
    )
    return ValidationReport(
        stage=WORKFLOW_EXECUTABLE_STAGE,
        issues=tuple(issues),
    )


def mcp_tool_admission_report(
    payload: object,
    *,
    mcp_tool: dict[str, Any],
) -> ValidationReport:
    owner_id = str(mcp_tool.get("id", ""))
    owner_name = str(mcp_tool.get("name", ""))
    admission, _document = admit_workflow_document(payload)
    return ValidationReport(
        stage=admission.stage,
        issues=tuple(
            _mcp_tool_issue(issue, owner_id=owner_id, owner_name=owner_name)
            for issue in admission.issues
        ),
    )


def validate_stored_mcp_tool(
    mcp_tool: dict[str, Any],
    *,
    blocks: BlockStore,
    configuration_validation: WorkflowConfigurationValidator,
    stage: str,
) -> ValidationReport:
    owner_id = str(mcp_tool.get("id", ""))
    owner_name = str(mcp_tool.get("name", ""))
    try:
        stored = StoredMcpToolConfiguration.model_validate(
            {key: value for key, value in mcp_tool.items() if key != "id"}
        )
    except ValidationError as exc:
        return report_from_validation_error(
            exc,
            stage=stage,
            scope="mcp_tool",
            owner_id=owner_id,
            owner_name=owner_name,
            owner_type="mcp_tool",
        )

    document = WorkflowGraphDocumentV1(
        definition=stored.definition,
        layout=stored.layout,
    )
    admission, normalized = admit_workflow_document(document)
    issues = [
        _mcp_tool_issue(issue, owner_id=owner_id, owner_name=owner_name)
        for issue in admission.issues
    ]
    if normalized is not None and stored.enabled:
        issues.extend(
            mcp_tool_executable_report(
                normalized,
                mcp_tool={
                    "id": owner_id,
                    "name": stored.name,
                },
                blocks=blocks,
                configuration_validation=configuration_validation,
            ).issues
        )
    elif normalized is not None:
        issues.extend(
            _lifecycle_dependency_issues(
                normalized,
                owner_id=owner_id,
                owner_name=owner_name,
            )
        )
    return ValidationReport(stage=stage, issues=tuple(issues))


__all__ = [
    "StoredMcpToolConfiguration",
    "mcp_tool_admission_report",
    "mcp_tool_executable_report",
    "validate_stored_mcp_tool",
]
