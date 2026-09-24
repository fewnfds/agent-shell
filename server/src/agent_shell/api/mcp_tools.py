from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_shell.api.configuration_collections import (
    configuration_collection,
    configuration_collection_requested,
    matches_configuration_query,
)
from agent_shell.api.errors import management_error
from agent_shell.configuration.identity import ConfigurationName
from agent_shell.mcp_tool_contracts import McpToolDefinition
from agent_shell.mcp_tools.publication import McpToolPublicationService
from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.mcp_tools import McpToolStore
from agent_shell.validation import report_from_validation_error
from agent_shell.validation.mcp_tools import (
    mcp_tool_admission_report,
    mcp_tool_executable_report,
)
from agent_shell.validation.models import ValidationReport, validation_failure_detail
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.workflow.validation import WORKFLOW_ADMISSION_STAGE, admit_workflow_document
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1


class McpToolCopy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: ConfigurationName


class McpToolBulkDelete(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ids: list[str] | None = Field(default=None, min_length=1)
    q: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def select_ids_or_query(self) -> "McpToolBulkDelete":
        if (self.ids is None) == (self.q is None):
            raise ValueError("exactly one of ids or q is required")
        return self


def _validated(payload: dict, *, blocks: BlockStore) -> dict:
    try:
        validated = McpToolDefinition.model_validate(payload).model_dump(
            mode="json"
        )
    except ValidationError as exc:
        raise management_error(
            422,
            code="mcp_tool_invalid",
            message_key="errors.mcpToolInvalid",
            message="The MCP Tool configuration is invalid.",
            message_args={"count": len(exc.errors())},
        ) from exc
    python_schema_id = validated["python_schema_id"]
    if (
        python_schema_id is not None
        and blocks.get_block("python-schema", python_schema_id) is None
    ):
        raise management_error(
            422,
            code="python_schema_not_found",
            message_key="errors.pythonSchemaNotFound",
            message="The selected Python Schema Component does not exist.",
        )
    return validated


async def _repair_publication(
    publication: McpToolPublicationService,
    diagnostics: RuntimeDiagnostics,
) -> None:
    """Best-effort alignment after a cross-store mutation aborts."""

    try:
        await publication.reconcile()
    except Exception as exc:
        # The original operation already failed. Startup and repository
        # activation retain the same canonical reconciliation boundary.
        await diagnostics.aruntime_error(
            exc,
            code="mcp_tool_publication_repair_failed",
            component="persistence",
        )


async def _withdraw_items(
    publication: McpToolPublicationService,
    diagnostics: RuntimeDiagnostics,
    item_ids: list[str],
    *,
    message: str,
) -> None:
    try:
        for item_id in item_ids:
            await publication.delete(item_id)
    except Exception as exc:
        await _repair_publication(publication, diagnostics)
        raise management_error(
            502,
            code="mcp_tool_publication_failed",
            message_key="errors.mcpToolPublicationFailed",
            message=message,
        ) from exc


def _save_metadata(
    store: McpToolStore,
    blocks: BlockStore,
    configuration_validation: ConfigurationValidationService,
    item_id: str,
    payload: dict,
    *,
    expected_repository_id: str,
) -> dict:
    existing = store.get_item(item_id)
    validated = _validated(payload, blocks=blocks)
    validated["enabled"] = existing["enabled"] if existing is not None else False
    if existing is not None and validated["enabled"]:
        document = store.get_graph(item_id)
        assert document is not None
        report = _validate_graph(
            document,
            mcp_tool={"id": item_id, **validated},
            blocks=blocks,
            configuration_validation=configuration_validation,
        )
        if not report.valid:
            raise HTTPException(
                status_code=422,
                detail=validation_failure_detail(report),
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
            code="mcp_tool_name_conflict",
            message_key="errors.mcpToolNameConflict",
            message="An MCP Tool with this name already exists.",
        ) from exc
    item = store.get_item(item_id)
    assert item is not None
    return item


def _validate_graph(
    document: WorkflowGraphDocumentV1,
    *,
    mcp_tool: dict,
    blocks: BlockStore,
    configuration_validation: ConfigurationValidationService,
) -> ValidationReport:
    return mcp_tool_executable_report(
        document,
        mcp_tool=mcp_tool,
        blocks=blocks,
        configuration_validation=configuration_validation,
        include_draft_admission=True,
    )


def _update_graph(
    store: McpToolStore,
    blocks: BlockStore,
    configuration_validation: ConfigurationValidationService,
    item_id: str,
    payload: dict,
) -> tuple[dict, WorkflowGraphDocumentV1, WorkflowGraphDocumentV1, bool, str]:
    expected_repository_id = store.repository_id()
    mcp_tool = store.get_item(item_id)
    if mcp_tool is None:
        raise management_error(
            404,
            code="mcp_tool_not_found",
            message_key="errors.mcpToolNotFound",
            message="The MCP Tool does not exist.",
        )
    previous_document = store.get_graph(item_id)
    assert previous_document is not None
    admission, document = admit_workflow_document(payload)
    if document is None:
        raise HTTPException(
            status_code=422,
            detail=validation_failure_detail(
                mcp_tool_admission_report(
                    payload,
                    mcp_tool=mcp_tool,
                )
            ),
        )
    report = _validate_graph(
        document,
        mcp_tool=mcp_tool,
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
        expected_repository_id=expected_repository_id,
    ):
        raise management_error(
            404,
            code="mcp_tool_not_found",
            message_key="errors.mcpToolNotFound",
            message="The MCP Tool does not exist.",
        )
    return (
        document.model_dump(mode="json"),
        document,
        previous_document,
        bool(mcp_tool["enabled"]),
        expected_repository_id,
    )


def build_mcp_tool_router(
    store: McpToolStore,
    blocks: BlockStore,
    configuration_validation: ConfigurationValidationService,
    publication: McpToolPublicationService,
    diagnostics: RuntimeDiagnostics,
    publication_commands: asyncio.Lock,
) -> APIRouter:
    from agent_shell.http_surface import management_api_router

    router = management_api_router()

    @router.get("/mcp-tools")
    def list_mcp_tools(
        request: Request,
        view: Literal["full", "summary"] = "full",
        q: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int | None, Query(ge=1)] = None,
    ) -> list[dict] | dict:
        items = store.list_items()
        if not configuration_collection_requested(request.query_params):
            return items
        return configuration_collection(
            items,
            repository_context=store.repository_context(),
            query=q,
            search_fields=("name", "description", "id"),
            offset=offset,
            limit=limit,
        )

    @router.post("/mcp-tools")
    def create_mcp_tool(payload: dict) -> dict:
        expected_repository_id = store.repository_id()
        return _save_metadata(
            store,
            blocks,
            configuration_validation,
            store.new_id(),
            payload,
            expected_repository_id=expected_repository_id,
        )

    @router.get("/mcp-tools/{item_id}")
    def get_mcp_tool(item_id: str) -> dict:
        item = store.get_item(item_id)
        if item is None:
            raise management_error(
                404,
                code="mcp_tool_not_found",
                message_key="errors.mcpToolNotFound",
                message="The MCP Tool does not exist.",
            )
        return item

    @router.put("/mcp-tools/{item_id}")
    async def update_mcp_tool(item_id: str, payload: dict) -> dict:
        def update_metadata() -> tuple[dict, dict, str]:
            expected_repository_id = store.repository_id()
            previous = store.get_item(item_id)
            if previous is None:
                raise management_error(
                    404,
                    code="mcp_tool_not_found",
                    message_key="errors.mcpToolNotFound",
                    message="The MCP Tool does not exist.",
                )
            result = _save_metadata(
                store,
                blocks,
                configuration_validation,
                item_id,
                payload,
                expected_repository_id=expected_repository_id,
            )
            return previous, result, expected_repository_id

        async with publication_commands:
            previous, result, expected_repository_id = await asyncio.to_thread(
                update_metadata
            )
            if result["enabled"]:
                try:
                    await publication.publish(item_id)
                except Exception as exc:
                    await asyncio.to_thread(
                        store.save_item,
                        item_id,
                        previous,
                        expected_repository_id=expected_repository_id,
                    )
                    await _repair_publication(publication, diagnostics)
                    raise management_error(
                        502,
                        code="mcp_tool_publication_failed",
                        message_key="errors.mcpToolPublicationFailed",
                        message="The MCP Tool Assistant could not be published.",
                    ) from exc
            return result

    @router.post("/mcp-tools/{item_id}/copy")
    def copy_mcp_tool(item_id: str, payload: McpToolCopy) -> dict:
        expected_repository_id = store.repository_id()
        source = store.get_item(item_id)
        if source is None:
            raise management_error(
                404,
                code="mcp_tool_not_found",
                message_key="errors.mcpToolNotFound",
                message="The MCP Tool does not exist.",
            )
        candidate = {
            "name": payload.name,
            "description": source["description"],
            "python_schema_id": source["python_schema_id"],
        }
        validated = _validated(candidate, blocks=blocks)
        copy_id = store.new_id()
        try:
            copied = store.copy_item(
                item_id,
                copy_id,
                validated,
                expected_repository_id=expected_repository_id,
            )
        except ValueError as exc:
            raise management_error(
                409,
                code="mcp_tool_name_conflict",
                message_key="errors.mcpToolNameConflict",
                message="An MCP Tool with this name already exists.",
            ) from exc
        if not copied:
            raise management_error(
                404,
                code="mcp_tool_not_found",
                message_key="errors.mcpToolNotFound",
                message="The MCP Tool does not exist.",
            )
        result = store.get_item(copy_id)
        assert result is not None
        return result

    @router.post("/mcp-tools/delete")
    async def delete_mcp_tools(payload: McpToolBulkDelete) -> dict[str, int]:
        def selected_ids() -> tuple[list[str], str]:
            expected_repository_id = store.repository_id()
            summaries = store.list_item_summaries()
            ids = (
                list(dict.fromkeys(payload.ids))
                if payload.ids is not None
                else [
                    str(item["id"])
                    for item in summaries
                    if matches_configuration_query(
                        item,
                        payload.q or "",
                        ("name", "description", "id"),
                    )
                ]
            )
            if any(store.get_item(item_id) is None for item_id in ids):
                raise management_error(
                    404,
                    code="mcp_tool_not_found",
                    message_key="errors.mcpToolNotFound",
                    message="An MCP Tool does not exist.",
                )
            return ids, expected_repository_id

        async with publication_commands:
            ids, expected_repository_id = await asyncio.to_thread(selected_ids)
            await _withdraw_items(
                publication,
                diagnostics,
                ids,
                message="The MCP Tool Assistant could not be withdrawn.",
            )
            try:
                deleted = await asyncio.to_thread(
                    store.delete_items,
                    ids,
                    expected_repository_id=expected_repository_id,
                )
            except Exception:
                await _repair_publication(publication, diagnostics)
                raise
            return {"deleted": deleted}

    @router.get("/mcp-tools/{item_id}/graph")
    def get_mcp_tool_graph(item_id: str) -> dict:
        document = store.get_graph(item_id)
        if document is None or store.get_item(item_id) is None:
            raise management_error(
                404,
                code="mcp_tool_not_found",
                message_key="errors.mcpToolNotFound",
                message="The MCP Tool does not exist.",
            )
        return document.model_dump(mode="json")

    @router.put("/mcp-tools/{item_id}/draft")
    async def update_mcp_tool_draft(item_id: str, payload: dict) -> dict:
        def parse_draft() -> tuple[WorkflowGraphDocumentV1, str]:
            expected_repository_id = store.repository_id()
            mcp_tool = store.get_item(item_id)
            if mcp_tool is None:
                raise management_error(
                    404,
                    code="mcp_tool_not_found",
                    message_key="errors.mcpToolNotFound",
                    message="The MCP Tool does not exist.",
                )
            try:
                document = WorkflowGraphDocumentV1.model_validate(payload)
            except ValidationError as exc:
                report = report_from_validation_error(
                    exc,
                    stage=WORKFLOW_ADMISSION_STAGE,
                    scope="mcp_tool",
                    owner_id=str(mcp_tool["id"]),
                    owner_name=str(mcp_tool["name"]),
                    owner_type="mcp_tool",
                )
                raise HTTPException(
                    status_code=422,
                    detail=validation_failure_detail(report),
                ) from exc
            return document, expected_repository_id

        async with publication_commands:
            document, expected_repository_id = await asyncio.to_thread(
                parse_draft
            )
            await _withdraw_items(
                publication,
                diagnostics,
                [item_id],
                message="The MCP Tool Assistant could not be withdrawn.",
            )

            def save_draft() -> dict:
                if not store.save_graph_and_enabled(
                    item_id,
                    document,
                    enabled=False,
                    expected_repository_id=expected_repository_id,
                ):
                    raise management_error(
                        404,
                        code="mcp_tool_not_found",
                        message_key="errors.mcpToolNotFound",
                        message="The MCP Tool does not exist.",
                    )
                return document.model_dump(mode="json")

            try:
                return await asyncio.to_thread(save_draft)
            except Exception:
                await _repair_publication(publication, diagnostics)
                raise

    @router.post("/mcp-tools/{item_id}/validate")
    def validate_mcp_tool(item_id: str, payload: dict) -> dict:
        if store.get_item(item_id) is None:
            raise management_error(
                404,
                code="mcp_tool_not_found",
                message_key="errors.mcpToolNotFound",
                message="The MCP Tool does not exist.",
            )
        admission, document = admit_workflow_document(payload)
        if document is None:
            return mcp_tool_admission_report(
                payload,
                mcp_tool=store.get_item(item_id) or {},
            ).as_dict()
        return _validate_graph(
            document,
            mcp_tool=store.get_item(item_id) or {},
            blocks=blocks,
            configuration_validation=configuration_validation,
        ).as_dict()

    @router.put("/mcp-tools/{item_id}/graph")
    async def update_mcp_tool_graph(item_id: str, payload: dict) -> dict:
        async with publication_commands:
            (
                result,
                _document,
                previous_document,
                previous_enabled,
                expected_repository_id,
            ) = await asyncio.to_thread(
                _update_graph,
                store,
                blocks,
                configuration_validation,
                item_id,
                payload,
            )
            try:
                await publication.publish(item_id)
            except Exception as exc:
                await asyncio.to_thread(
                    store.save_graph_and_enabled,
                    item_id,
                    previous_document,
                    enabled=previous_enabled,
                    expected_repository_id=expected_repository_id,
                )
                await _repair_publication(publication, diagnostics)
                raise management_error(
                    502,
                    code="mcp_tool_publication_failed",
                    message_key="errors.mcpToolPublicationFailed",
                    message="The MCP Tool Assistant could not be published.",
                ) from exc
            return result

    @router.delete("/mcp-tools/{item_id}")
    async def delete_mcp_tool(item_id: str) -> dict[str, bool]:
        def require_item() -> str:
            expected_repository_id = store.repository_id()
            if store.get_item(item_id) is None:
                raise management_error(
                    404,
                    code="mcp_tool_not_found",
                    message_key="errors.mcpToolNotFound",
                    message="The MCP Tool does not exist.",
                )
            return expected_repository_id

        async with publication_commands:
            expected_repository_id = await asyncio.to_thread(require_item)
            await _withdraw_items(
                publication,
                diagnostics,
                [item_id],
                message="The MCP Tool Assistant could not be withdrawn.",
            )
            try:
                deleted = await asyncio.to_thread(
                    store.delete_item,
                    item_id,
                    expected_repository_id=expected_repository_id,
                )
            except Exception:
                await _repair_publication(publication, diagnostics)
                raise
            if not deleted:
                await _repair_publication(publication, diagnostics)
                raise management_error(
                    404,
                    code="mcp_tool_not_found",
                    message_key="errors.mcpToolNotFound",
                    message="The MCP Tool does not exist.",
                )
            return {"ok": True}

    return router


__all__ = ["build_mcp_tool_router"]
