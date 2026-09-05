from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langchain_core.runnables import RunnableConfig
from langgraph_sdk import Auth
from langgraph_sdk.runtime import ServerRuntime

from agent_shell.app import create_app
from agent_shell.runtime.context import WorkflowRunContext, WorkflowRuntimeContext
from agent_shell.runtime.request_snapshot import LANGGRAPH_WORKFLOW_GRAPH_ID
from agent_shell.security import (
    SecurityFailure,
    authenticate_bearer_token,
    parse_bearer_authorization,
)
from agent_shell.settings import Settings


GRAPH_ID = LANGGRAPH_WORKFLOW_GRAPH_ID

app: FastAPI | None = None
_settings: Settings | None = None


def configure_runtime(settings: Settings, *, serve_frontend: bool) -> FastAPI:
    """Create the one custom app before LangGraph resolves config exports."""

    global app, _settings
    _settings = settings
    app = create_app(settings=settings, serve_frontend=serve_frontend)
    return app


def _require_app() -> FastAPI:
    if app is None:
        raise RuntimeError(
            "LangGraph Dev runtime must be configured by the Agent Shell launcher"
        )
    return app


auth = Auth()


@auth.authenticate
async def authenticate(authorization: str | None) -> Auth.types.MinimalUserDict:
    """Protect every official route with the canonical management credential."""

    settings = _settings
    if settings is None or settings.management_token is None:
        raise Auth.exceptions.HTTPException(status_code=503, detail="Unavailable")
    try:
        candidate = parse_bearer_authorization(authorization or "")
        authenticate_bearer_token(
            candidate,
            "management",
            management_token=settings.management_token.get_secret_value(),
            api_key=None,
        )
    except SecurityFailure as exc:
        raise Auth.exceptions.HTTPException(
            status_code=exc.status_code,
            detail=exc.safe_message,
        ) from None
    return {
        "identity": "agent-shell",
        "display_name": "Agent Shell",
        "is_authenticated": True,
        "permissions": ["agent-shell:execute"],
    }


@auth.on
async def authorize_single_owner(
    ctx: Auth.types.AuthContext,
    value: dict[str, Any],
) -> dict[str, str]:
    """Keep all official resources inside this single-user instance."""

    del ctx
    metadata = value.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["owner"] = "agent-shell"
    return {"owner": "agent-shell"}


def _factory_inputs(config: RunnableConfig) -> tuple[str, dict[str, Any]]:
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        raise ValueError("Workflow Assistant configurable values are missing")
    workflow_id = configurable.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise ValueError("Workflow Assistant workflow_id is missing")
    return workflow_id, dict(configurable)


def _execution_context(
    runtime: ServerRuntime,
    *,
    workflow_id: str,
    configurable: Mapping[str, Any] | None = None,
) -> WorkflowRuntimeContext:
    values: Mapping[str, Any] = {}
    if execution_runtime := runtime.execution_runtime:
        raw = execution_runtime.context
        if isinstance(raw, WorkflowRunContext):
            values = {
                "request_id": raw.request_id,
                "lifecycle_id": raw.lifecycle_id,
                "caller_run_id": raw.caller_run_id,
                "operation_id": raw.operation_id,
            }
        elif isinstance(raw, Mapping):
            values = raw
        elif raw is not None:
            raise ValueError("Workflow Run context is invalid")
    configured = configurable or {}
    return WorkflowRuntimeContext(
        request_id=str(values.get("request_id") or configured.get("request_id") or ""),
        lifecycle_id=str(
            values.get("lifecycle_id") or configured.get("lifecycle_id") or ""
        ),
        workflow_id=workflow_id,
        caller_run_id=str(
            values.get("caller_run_id") or configured.get("caller_run_id") or ""
        ),
        operation_id=str(
            values.get("operation_id") or configured.get("operation_id") or ""
        ),
    )


@asynccontextmanager
async def workflow_graph(
    config: RunnableConfig,
    runtime: ServerRuntime,
) -> AsyncIterator[Any]:
    """Build one current Workflow for Agent Server execution or inspection."""

    application = _require_app()
    workflow_id, configurable = _factory_inputs(config)
    context = _execution_context(
        runtime,
        workflow_id=workflow_id,
        configurable=configurable,
    )
    coordinator = application.state.agent_runtime.active_lifecycle(
        context.lifecycle_id
    )
    if coordinator is not None:
        graph = await coordinator.build_server_graph(
            workflow_id=workflow_id,
            store=runtime.store,
            context=context,
        )
        yield graph
        return

    snapshot = await application.state.agent_runtime.capture()
    workflow = snapshot.workflow_by_id(workflow_id)
    document = snapshot.workflow_document(workflow_id)
    if workflow is None or not workflow.get("enabled") or document is None:
        raise ValueError("Workflow is absent or disabled")

    graph_runtime = snapshot.new_runtime(store=runtime.store)
    if runtime.execution_runtime is None:
        graph = await asyncio.to_thread(
            graph_runtime.build_workflow_structure,
            document,
            workflow_snapshot=workflow,
            server_context=context,
        )
        yield graph
        return

    execution = await graph_runtime.start_workflow(
        document,
        [],
        workflow_snapshot=workflow,
        request_id=context.request_id,
        public_model=str(workflow["name"]),
        lifecycle_id=context.lifecycle_id,
        caller_run_id=context.caller_run_id,
        operation_id=context.operation_id,
        public_output=False,
        response_consumer=False,
        server_context=context,
    )
    try:
        yield execution.graph
    finally:
        await execution.close_resources()


__all__ = ["GRAPH_ID", "app", "auth", "configure_runtime", "workflow_graph"]
