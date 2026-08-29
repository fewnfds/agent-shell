from __future__ import annotations

from typing import Annotated, Any, Protocol

from pydantic import Field, ValidationError

from agent_shell.storage.blocks import BlockStore
from agent_shell.validation.contracts import report_from_validation_error
from agent_shell.validation.models import ValidationIssue, ValidationReport
from agent_shell.workflow.catalog import CommandNodeConfig
from agent_shell.workflow.contracts import (
    WorkflowGraphDefinitionV1,
    WorkflowGraphDocumentV1,
    WorkflowLayoutV1,
)
from agent_shell.workflow.validation import (
    WORKFLOW_EXECUTABLE_STAGE,
    admit_workflow_document,
    validate_workflow_executable,
)
from agent_shell.workflow_contracts import WorkflowDefinition


class WorkflowConfigurationValidator(Protocol):
    def validate_stored_block(
        self,
        block_type: str,
        payload: dict[str, Any],
        *,
        stage: str,
        check_dependencies: bool = True,
    ) -> ValidationReport: ...

    def resolve_main_agent(
        self,
        main_agent_id: str,
        *,
        stage: str = "request_assembly",
    ) -> tuple[ValidationReport, object | None]: ...

    def reference_issue(
        self,
        *,
        scope: str,
        owner_id: str,
        owner_name: str,
        owner_type: str,
        path: str,
        reference_id: str,
        expected_type: str,
    ) -> ValidationIssue: ...


class StoredWorkflowConfiguration(WorkflowDefinition):
    enabled: Annotated[bool, Field(strict=True)]
    definition: WorkflowGraphDefinitionV1
    layout: WorkflowLayoutV1


def _component_reference_issue(
    validation: WorkflowConfigurationValidator,
    *,
    workflow: dict[str, Any],
    path: str,
    reference_id: str,
    expected_type: str,
) -> ValidationIssue:
    return validation.reference_issue(
        scope="workflow",
        owner_id=str(workflow.get("id", "")),
        owner_name=str(workflow.get("name", "")),
        owner_type="workflow",
        path=path,
        reference_id=reference_id,
        expected_type=expected_type,
    )


def workflow_executable_report(
    document: WorkflowGraphDocumentV1,
    *,
    workflow: dict[str, Any],
    blocks: BlockStore,
    configuration_validation: WorkflowConfigurationValidator,
) -> ValidationReport:
    commands: dict[str, object] = {}
    referenced_issues: list[ValidationIssue] = []
    component_reports: dict[tuple[str, str], ValidationReport] = {}

    def project_component_issues(path: str, report: ValidationReport) -> None:
        for issue in report.issues:
            referenced_issues.append(
                ValidationIssue(
                    code=issue.code,
                    scope="workflow",
                    owner_id=str(workflow.get("id", "")),
                    owner_name=str(workflow.get("name", "")),
                    owner_type="workflow",
                    path=path,
                    message=issue.message,
                    message_key=issue.message_key,
                    message_args=issue.message_args,
                    severity=issue.severity,
                )
            )

    checkpointer_id = workflow.get("checkpointer_id")
    if checkpointer_id is not None:
        stored_checkpointer = blocks.get_block_internal(
            "checkpointer",
            str(checkpointer_id),
        )
        if stored_checkpointer is None:
            referenced_issues.append(
                _component_reference_issue(
                    configuration_validation,
                    workflow=workflow,
                    path="checkpointer_id",
                    reference_id=str(checkpointer_id),
                    expected_type="checkpointer",
                )
            )
        else:
            project_component_issues(
                "checkpointer_id",
                configuration_validation.validate_stored_block(
                    "checkpointer",
                    stored_checkpointer,
                    stage=WORKFLOW_EXECUTABLE_STAGE,
                    check_dependencies=True,
                ),
            )

    workflow_event_output_id = workflow.get("workflow_event_output_id")
    if workflow_event_output_id is not None:
        stored_output = blocks.get_block_internal(
            "workflow-event-output",
            str(workflow_event_output_id),
        )
        if stored_output is None:
            referenced_issues.append(
                _component_reference_issue(
                    configuration_validation,
                    workflow=workflow,
                    path="workflow_event_output_id",
                    reference_id=str(workflow_event_output_id),
                    expected_type="workflow-event-output",
                )
            )
        else:
            output_report = configuration_validation.validate_stored_block(
                "workflow-event-output",
                stored_output,
                stage=WORKFLOW_EXECUTABLE_STAGE,
                check_dependencies=True,
            )
            project_component_issues("workflow_event_output_id", output_report)

    scheduling_id = workflow.get("response_stream_scheduling_id")
    if scheduling_id is not None:
        stored_scheduling = blocks.get_block_internal(
            "response-stream-scheduling",
            str(scheduling_id),
        )
        if stored_scheduling is None:
            referenced_issues.append(
                _component_reference_issue(
                    configuration_validation,
                    workflow=workflow,
                    path="response_stream_scheduling_id",
                    reference_id=str(scheduling_id),
                    expected_type="response-stream-scheduling",
                )
            )
        else:
            scheduling_report = configuration_validation.validate_stored_block(
                "response-stream-scheduling",
                stored_scheduling,
                stage=WORKFLOW_EXECUTABLE_STAGE,
                check_dependencies=True,
            )
            project_component_issues(
                "response_stream_scheduling_id",
                scheduling_report,
            )

    def component_report(
        block_type: str,
        reference: str,
        stored: dict[str, Any],
    ) -> ValidationReport:
        key = (block_type, reference)
        report = component_reports.get(key)
        if report is None:
            report = configuration_validation.validate_stored_block(
                block_type,
                stored,
                stage=WORKFLOW_EXECUTABLE_STAGE,
            )
            component_reports[key] = report
        return report

    def project_component_report(
        *,
        node_id: str,
        node_type: str,
        node_index: int,
        reference_field: str,
        report: ValidationReport,
    ) -> None:
        for issue in report.issues:
            referenced_issues.append(
                ValidationIssue(
                    code=issue.code,
                    scope="workflow",
                    owner_id=node_id,
                    owner_name=node_id,
                    owner_type=node_type,
                    path=(
                        f"definition.nodes[{node_index}].config.{reference_field}"
                    ),
                    message=issue.message,
                    message_key=issue.message_key,
                    message_args=issue.message_args,
                    severity=issue.severity,
                )
            )

    for node_index, node in enumerate(document.definition.nodes):
        if node.type == "command":
            reference = CommandNodeConfig.model_validate(node.config).command_id
            stored = blocks.get_block_internal("command", reference)
            if stored is not None:
                report = component_report("command", reference, stored)
                project_component_report(
                    node_id=node.id,
                    node_type=node.type,
                    node_index=node_index,
                    reference_field="command_id",
                    report=report,
                )
                commands[node.id] = stored
            else:
                referenced_issues.append(
                    _component_reference_issue(
                        configuration_validation,
                        workflow=workflow,
                        path=f"definition.nodes[{node_index}].config.command_id",
                        reference_id=reference,
                        expected_type="command",
                    )
                )
                commands[node.id] = object()
    def validate_main_agent(main_agent_id: str) -> ValidationReport:
        report, _ = configuration_validation.resolve_main_agent(
            main_agent_id,
            stage=WORKFLOW_EXECUTABLE_STAGE,
        )
        return report

    executable = validate_workflow_executable(
        document,
        validate_main_agent=validate_main_agent,
        commands=commands,
        workflow_role=workflow["workflow_role"],
    )
    return ValidationReport(
        stage=WORKFLOW_EXECUTABLE_STAGE,
        issues=(*executable.issues, *referenced_issues),
    )


def validate_stored_workflow(
    workflow: dict[str, Any],
    *,
    blocks: BlockStore,
    configuration_validation: WorkflowConfigurationValidator,
    stage: str,
) -> ValidationReport:
    owner_id = str(workflow.get("id", ""))
    owner_name = str(workflow.get("name", ""))
    try:
        stored = StoredWorkflowConfiguration.model_validate(
            {key: value for key, value in workflow.items() if key != "id"}
        )
    except ValidationError as exc:
        return report_from_validation_error(
            exc,
            stage=stage,
            scope="workflow",
            owner_id=owner_id,
            owner_name=owner_name,
            owner_type="workflow",
        )

    document = WorkflowGraphDocumentV1(
        definition=stored.definition,
        layout=stored.layout,
    )
    admission, normalized = admit_workflow_document(
        document,
        workflow_role=stored.workflow_role,
    )
    issues = list(admission.issues)
    if stored.enabled and normalized is not None:
        issues.extend(
            workflow_executable_report(
                normalized,
                workflow=workflow,
                blocks=blocks,
                configuration_validation=configuration_validation,
            ).issues
        )
    return ValidationReport(stage=stage, issues=tuple(issues))


__all__ = [
    "StoredWorkflowConfiguration",
    "validate_stored_workflow",
    "workflow_executable_report",
]
