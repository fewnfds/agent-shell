from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from agent_shell.api.errors import management_error
from agent_shell.runtime.monitoring_read_service import (
    MonitoringCaptureDisabled,
    MonitoringInvocationNotFound,
    MonitoringLifecycleNotFound,
    MonitoringNodeNotFound,
    MonitoringReadError,
    MonitoringReadService,
    MonitoringReadUnavailable,
    MonitoringRunNotFound,
    MonitoringWorkflowNotFound,
)


NodeStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "incomplete",
]
ModelStatus = Literal["running", "completed", "failed"]
CommandPhase = Literal["started", "completed", "failed", "cancelled"]


class MonitoringSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: dict[str, object]
    read_at: str
    lifecycle: dict[str, object]
    summary: dict[str, object]
    runs: list[dict[str, object]]
    forest: dict[str, object]


class MonitoringResourceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    availability: Literal[
        "not_enabled",
        "unavailable",
        "capturing",
        "available",
        "partial",
        "pending",
        "not_applicable",
    ]
    read_at: str


def _http_error(exc: MonitoringReadError):
    if isinstance(exc, MonitoringLifecycleNotFound):
        return management_error(
            404,
            code="workflow_lifecycle_not_found",
            message_key="errors.workflowLifecycleNotFound",
            message="The Workflow lifecycle does not exist.",
        )
    if isinstance(exc, MonitoringRunNotFound):
        return management_error(
            404,
            code="workflow_run_not_found",
            message_key="errors.workflowRunNotFound",
            message="The Workflow Run does not exist in this lifecycle.",
        )
    if isinstance(exc, MonitoringWorkflowNotFound):
        return management_error(
            404,
            code="workflow_scope_not_found",
            message_key="errors.workflowScopeNotFound",
            message="The Workflow has no Run in this lifecycle.",
        )
    if isinstance(exc, MonitoringNodeNotFound):
        return management_error(
            404,
            code="workflow_node_not_found",
            message_key="errors.workflowNodeNotFound",
            message="The Workflow Node does not exist in this Run's frozen graph.",
        )
    if isinstance(exc, MonitoringInvocationNotFound):
        return management_error(
            404,
            code="agent_invocation_not_found",
            message_key="errors.agentInvocationNotFound",
            message="The Agent invocation does not exist in this Workflow Run.",
        )
    if isinstance(exc, MonitoringCaptureDisabled):
        return management_error(
            409,
            code="runtime_monitoring_disabled",
            message_key="errors.runtimeMonitoringDisabled",
            message="Runtime monitoring was disabled for this lifecycle.",
        )
    if isinstance(exc, MonitoringReadUnavailable):
        return management_error(
            503,
            code="runtime_monitoring_unavailable",
            message_key="errors.runtimeMonitoringUnavailable",
            message="The required runtime monitoring registry is unavailable.",
        )
    return management_error(
        500,
        code="runtime_monitoring_read_failed",
        message_key="errors.runtimeMonitoringReadFailed",
        message="The runtime monitoring request failed.",
    )


def build_runtime_monitoring_router(service: MonitoringReadService) -> APIRouter:
    router = APIRouter()
    prefix = "/api/workflow-lifecycles/{lifecycle_id}/monitoring"

    def read(call):
        try:
            return call()
        except MonitoringReadError as exc:
            raise _http_error(exc) from exc

    async def aread(call):
        try:
            return await call()
        except MonitoringReadError as exc:
            raise _http_error(exc) from exc

    @router.get(prefix + "/snapshot", response_model=MonitoringSnapshotResponse)
    async def snapshot(
        lifecycle_id: str,
        workflow_id: str | None = Query(default=None, min_length=1),
        run_id: str | None = Query(default=None, min_length=1),
    ):
        if workflow_id is not None and run_id is not None:
            raise management_error(
                422,
                code="runtime_monitoring_selector_conflict",
                message_key="errors.runtimeMonitoringSelectorConflict",
                message="Select either a Workflow or a Run, not both.",
            )
        scope = "run" if run_id else "workflow" if workflow_id else "lifecycle"
        selector_id = run_id or workflow_id
        return read(
            lambda: service.snapshot(
                lifecycle_id,
                scope=scope,
                selector_id=selector_id,
            )
        )

    @router.get(prefix + "/runs/{run_id}/graph", response_model=MonitoringResourceResponse)
    async def graph(lifecycle_id: str, run_id: str):
        return read(lambda: service.graph(lifecycle_id, run_id))

    @router.get(prefix + "/runs/{run_id}/nodes", response_model=MonitoringResourceResponse)
    async def nodes(
        lifecycle_id: str,
        run_id: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1),
        status: NodeStatus | None = Query(default=None),
    ):
        return read(
            lambda: service.node_summaries(
                lifecycle_id,
                run_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/nodes/{node_id}/attempts",
        response_model=MonitoringResourceResponse,
    )
    async def node_attempts(
        lifecycle_id: str,
        run_id: str,
        node_id: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1),
        status: NodeStatus | None = Query(default=None),
    ):
        return read(
            lambda: service.node_attempts(
                lifecycle_id,
                run_id,
                node_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/protocol-events",
        response_model=MonitoringResourceResponse,
    )
    async def protocol_events(
        lifecycle_id: str,
        run_id: str,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
        method: str | None = Query(default=None, min_length=1),
    ):
        return read(
            lambda: service.protocol_events(
                lifecycle_id,
                run_id,
                after_sequence=after_sequence,
                limit=limit,
                method=method,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/model-requests",
        response_model=MonitoringResourceResponse,
    )
    async def model_requests(
        lifecycle_id: str,
        run_id: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1),
        status: ModelStatus | None = Query(default=None),
    ):
        return read(
            lambda: service.model_requests(
                lifecycle_id,
                run_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/command-observations",
        response_model=MonitoringResourceResponse,
    )
    async def command_observations(
        lifecycle_id: str,
        run_id: str,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
        node_id: str | None = Query(default=None, min_length=1),
        phase: CommandPhase | None = Query(default=None),
    ):
        return read(
            lambda: service.command_observations(
                lifecycle_id,
                run_id,
                after_sequence=after_sequence,
                limit=limit,
                node_id=node_id,
                phase=phase,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/state",
        response_model=MonitoringResourceResponse,
    )
    async def state(lifecycle_id: str, run_id: str):
        return await aread(lambda: service.latest_state(lifecycle_id, run_id))

    @router.get(
        prefix + "/runs/{run_id}/agent-invocations/{invocation_id}",
        response_model=MonitoringResourceResponse,
    )
    async def agent_invocation(
        lifecycle_id: str,
        run_id: str,
        invocation_id: str,
    ):
        return await aread(
            lambda: service.agent_invocation(
                lifecycle_id,
                run_id,
                invocation_id,
            )
        )

    return router


__all__ = [
    "MonitoringResourceResponse",
    "MonitoringSnapshotResponse",
    "build_runtime_monitoring_router",
]
