from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_shell.api.errors import management_error
from agent_shell.api.configuration_collections import (
    configuration_collection,
    configuration_collection_requested,
    matches_configuration_query,
)
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.workflows import WorkflowStore
from agent_shell.validation import report_from_validation_error
from agent_shell.validation.models import ValidationReport, validation_failure_detail
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.validation.workflows import workflow_executable_report
from agent_shell.workflow.catalog import node_catalog_payload
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1
from agent_shell.workflow.validation import (
    WORKFLOW_ADMISSION_STAGE,
    admit_workflow_document,
)
from agent_shell.workflow_contracts import WorkflowDefinition, WorkflowRole


class WorkflowBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ids: list[str] | None = Field(default=None, min_length=1)
    q: str | None = Field(default=None, min_length=1)
    workflow_role: WorkflowRole | None = None

    @model_validator(mode="after")
    def select_ids_or_query(self) -> "WorkflowBulkDelete":
        if (self.ids is None) == (self.q is None):
            raise ValueError("exactly one of ids or q is required")
        if self.workflow_role is not None and self.q is None:
            raise ValueError("workflow_role is only valid with q")
        return self


class WorkflowCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)


def _validated(payload: dict) -> dict:
    try:
        return WorkflowDefinition.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise management_error(
            422,
            code="workflow_invalid",
            message_key="errors.workflowInvalid",
            message="The Workflow configuration is invalid.",
            message_args={"count": len(exc.errors())},
        ) from exc


def _save(
    store: WorkflowStore,
    blocks: BlockStore,
    item_id: str,
    payload: dict,
    *,
    expected_repository_id: str,
) -> dict:
    validated = _validated(payload)
    existing = store.get_item(item_id)
    validated["enabled"] = existing["enabled"] if existing is not None else False
    checkpointer_id = validated["checkpointer_id"]
    if (
        checkpointer_id is not None
        and blocks.get_block("checkpointer", checkpointer_id) is None
    ):
        raise management_error(
            422,
            code="workflow_checkpointer_not_found",
            message_key="errors.workflowCheckpointerNotFound",
            message="The selected Checkpointer component does not exist.",
        )
    event_output_id = validated["workflow_event_output_id"]
    if (
        event_output_id is not None
        and blocks.get_block("workflow-event-output", event_output_id) is None
    ):
        raise management_error(
            422,
            code="workflow_event_output_not_found",
            message_key="errors.workflowEventOutputNotFound",
            message="The selected event output component does not exist.",
        )
    try:
        store.save_item(
            item_id,
            validated,
            expected_repository_id=expected_repository_id,
        )
    except ValueError as exc:
        raise management_error(
            409,
            code="workflow_name_conflict",
            message_key="errors.workflowNameConflict",
            message="A Workflow with this name already exists.",
        ) from exc
    item = store.get_item(item_id)
    assert item is not None
    return item


def _parse_graph(
    payload: object,
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
    return ValidationReport(stage=WORKFLOW_ADMISSION_STAGE), document


def build_workflow_router(
    store: WorkflowStore,
    blocks: BlockStore,
    configuration_validation: ConfigurationValidationService,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/workflow-node-catalog")
    async def get_workflow_node_catalog() -> list[dict[str, object]]:
        return node_catalog_payload()

    @router.get("/api/workflows")
    async def list_workflows(
        request: Request,
        workflow_role: WorkflowRole | None = None,
        view: Literal["full", "summary"] = "full",
        q: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[dict] | dict:
        if not configuration_collection_requested(request.query_params):
            return store.list_items(workflow_role=workflow_role)
        items = (
            store.list_items(workflow_role=workflow_role)
            if view == "full"
            else store.list_item_summaries(workflow_role=workflow_role)
        )
        return configuration_collection(
            items,
            repository_context=store.repository_context(),
            query=q,
            search_fields=("name", "description", "id"),
            offset=offset,
            limit=limit,
        )

    @router.post("/api/workflows")
    async def create_workflow(payload: dict) -> dict:
        mutation_repository_id = store.repository_id()
        return _save(
            store,
            blocks,
            store.new_id(),
            payload,
            expected_repository_id=mutation_repository_id,
        )

    @router.post("/api/workflows/{item_id}/copy")
    async def copy_workflow(item_id: str, payload: WorkflowCopy) -> dict:
        mutation_repository_id = store.repository_id()
        source = store.get_item(item_id)
        if source is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        candidate = dict(source)
        candidate["name"] = payload.name
        candidate.pop("id", None)
        candidate.pop("enabled", None)
        validated = _validated(candidate)
        copy_id = store.new_id()
        try:
            copied = store.copy_item(
                item_id,
                copy_id,
                validated,
                expected_repository_id=mutation_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="workflow_name_conflict",
                message_key="errors.workflowNameConflict",
                message="A Workflow with this name already exists.",
            ) from exc
        if not copied:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        copied_item = store.get_item(copy_id)
        assert copied_item is not None
        return copied_item

    @router.post("/api/workflows/delete")
    async def delete_workflows(payload: WorkflowBulkDelete) -> dict[str, int]:
        mutation_repository_id = store.repository_id()
        ids = (
            list(dict.fromkeys(payload.ids))
            if payload.ids is not None
            else [
                str(item["id"])
                for item in store.list_item_summaries(
                    workflow_role=payload.workflow_role
                )
                if matches_configuration_query(
                    item, payload.q or "", ("name", "description", "id")
                )
            ]
        )
        if any(store.get_item(item_id) is None for item_id in ids):
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="A Workflow does not exist.",
            )
        return {
            "deleted": store.delete_items(
                ids, expected_repository_id=mutation_repository_id
            )
        }

    @router.get("/api/workflows/{item_id}")
    async def get_workflow(item_id: str) -> dict:
        item = store.get_item(item_id)
        if item is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return item

    @router.put("/api/workflows/{item_id}")
    async def update_workflow(item_id: str, payload: dict) -> dict:
        mutation_repository_id = store.repository_id()
        if store.get_item(item_id) is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return _save(
            store,
            blocks,
            item_id,
            payload,
            expected_repository_id=mutation_repository_id,
        )

    @router.get("/api/workflows/{item_id}/graph")
    async def get_workflow_graph(item_id: str) -> dict:
        document = store.get_graph(item_id)
        if document is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return document.model_dump(mode="json")

    @router.put("/api/workflows/{item_id}/graph")
    async def update_workflow_graph(item_id: str, payload: dict) -> dict:
        mutation_repository_id = store.repository_id()
        workflow = store.get_item(item_id)
        if workflow is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        admission, document = admit_workflow_document(
            payload,
            workflow_role=workflow["workflow_role"],
        )
        if document is None:
            raise HTTPException(
                status_code=422,
                detail=validation_failure_detail(admission),
            )
        report = workflow_executable_report(
            document,
            workflow=workflow,
            blocks=blocks,
            configuration_validation=configuration_validation,
        )
        if not report.valid:
            raise HTTPException(
                status_code=422,
                detail=validation_failure_detail(report),
            )
        if not store.save_graph_and_enabled(
            item_id,
            document,
            enabled=True,
            expected_repository_id=mutation_repository_id,
        ):
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return document.model_dump(mode="json")

    @router.put("/api/workflows/{item_id}/draft")
    async def update_workflow_draft(item_id: str, payload: dict) -> dict:
        mutation_repository_id = store.repository_id()
        if store.get_item(item_id) is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        report, document = _parse_graph(payload)
        if document is None:
            raise HTTPException(
                status_code=422,
                detail=validation_failure_detail(report),
            )
        if not store.save_graph_and_enabled(
            item_id,
            document,
            enabled=False,
            expected_repository_id=mutation_repository_id,
        ):
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return document.model_dump(mode="json")

    @router.post("/api/workflows/{item_id}/validate")
    async def validate_workflow(item_id: str, payload: dict) -> dict:
        workflow = store.get_item(item_id)
        if workflow is None:
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        admission, document = admit_workflow_document(
            payload,
            workflow_role=workflow["workflow_role"],
        )
        if document is None:
            return admission.as_dict()
        return workflow_executable_report(
            document,
            workflow=workflow,
            blocks=blocks,
            configuration_validation=configuration_validation,
        ).as_dict()

    @router.delete("/api/workflows/{item_id}")
    async def delete_workflow(item_id: str) -> dict[str, bool]:
        mutation_repository_id = store.repository_id()
        if not store.delete_item(
            item_id, expected_repository_id=mutation_repository_id
        ):
            raise management_error(
                404,
                code="workflow_not_found",
                message_key="errors.workflowNotFound",
                message="The Workflow does not exist.",
            )
        return {"ok": True}

    return router
