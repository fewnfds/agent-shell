from __future__ import annotations

from typing import Any, Literal

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
RunStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
ModelStatus = Literal["running", "completed", "failed"]
CommandPhase = Literal["started", "completed", "failed", "cancelled"]
PartitionStatus = Literal["capturing", "available", "partial", "not_applicable"]
Availability = Literal[
    "not_enabled",
    "unavailable",
    "capturing",
    "available",
    "partial",
    "pending",
    "not_applicable",
]
ScopeKind = Literal["lifecycle", "workflow", "run"]
ProtocolSourceType = Literal["agent", "subagent", "script", "non_agent"]


class MonitoringResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenUsage(MonitoringResponseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class MonitoringPartitionStates(MonitoringResponseModel):
    graph: PartitionStatus
    node: PartitionStatus
    protocol: PartitionStatus
    model: PartitionStatus
    command: PartitionStatus
    created_at: str
    updated_at: str


class MonitoringLifecycle(MonitoringResponseModel):
    lifecycle_id: str
    request_id: str
    root_run_id: str
    workflow_id: str
    workflow_name: str
    created_at: str
    lifecycle_status: Literal["active", "purge_pending", "deleting"]
    root_status: RunStatus
    monitoring_capture_enabled: bool
    fully_terminal_at: str | None
    message_count: int


class MonitoringRun(MonitoringResponseModel):
    run_id: str
    lifecycle_id: str
    request_id: str
    checkpoint_thread_id: str | None
    workflow_id: str
    workflow_name: str
    parent_run_id: str | None
    background_task_id: str | None
    run_depth: int
    status: RunStatus
    created_at: str
    started_at: str | None
    finished_at: str | None
    finish_reason: str
    error_code: str
    usage: TokenUsage
    monitoring: MonitoringPartitionStates | None


class MonitoringSelector(MonitoringResponseModel):
    scope: ScopeKind
    id: str | None


class MonitoringPartitionAvailability(MonitoringResponseModel):
    graph: Availability
    node: Availability
    protocol: Availability
    model: Availability
    command: Availability


class MonitoringSummary(MonitoringResponseModel):
    run_count: int
    active_run_count: int
    failed_run_count: int
    run_status_counts: dict[str, int]
    node_attempt_status_counts: dict[str, int]
    usage: TokenUsage
    partition_availability: MonitoringPartitionAvailability


class RunRelationship(MonitoringResponseModel):
    parent_run_id: str
    child_run_id: str


class RunForest(MonitoringResponseModel):
    root_run_ids: list[str]
    relationships: list[RunRelationship]
    orphan_run_ids: list[str]
    relationship_availability: Literal["available", "partial"]


class MonitoringSnapshotResponse(MonitoringResponseModel):
    selector: MonitoringSelector
    read_at: str
    lifecycle: MonitoringLifecycle
    summary: MonitoringSummary
    runs: list[MonitoringRun]
    forest: RunForest


class MonitoringResourceResponse(MonitoringResponseModel):
    availability: Availability
    read_at: str


class MonitoringGraph(MonitoringResponseModel):
    run_id: str
    lifecycle_id: str
    workflow_id: str
    workflow_name: str
    document_sha: str
    document: dict[str, Any]
    created_at: str


class MonitoringGraphResponse(MonitoringResourceResponse):
    graph: MonitoringGraph | None


class NodeSummary(MonitoringResponseModel):
    workflow_node_id: str
    first_sequence: int
    latest_sequence: int
    first_started_at: str
    latest_started_at: str
    attempt_count: int
    status_counts: dict[str, int]


class NodeSummaryPageResponse(MonitoringResourceResponse):
    items: list[NodeSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class NodeAttempt(MonitoringResponseModel):
    sequence: int
    lifecycle_id: str
    run_id: str
    workflow_node_id: str
    invocation_id: str
    attempt: int
    node_first_attempt_time: float | None
    started_at: str
    finished_at: str | None
    status: NodeStatus
    error_code: str


class NodeAttemptPageResponse(MonitoringResourceResponse):
    items: list[NodeAttempt]
    page: int
    page_size: int
    total: int
    total_pages: int


class ProtocolEventOrigin(MonitoringResponseModel):
    source_type: ProtocolSourceType
    workflow_node_id: str
    node_invocation_id: str
    agent_profile_id: str
    subagent_profile_id: str


class ProtocolEvent(MonitoringResponseModel):
    sequence: int
    method: str
    captured_at: str
    envelope: dict[str, Any]
    origin: ProtocolEventOrigin


class ProtocolEventSequenceResponse(MonitoringResourceResponse):
    items: list[ProtocolEvent]
    after_sequence: int
    next_after_sequence: int
    limit: int
    remaining: int


class ModelRequest(MonitoringResponseModel):
    sequence: int
    model_run_id: str
    started_at: str
    finished_at: str | None
    status: ModelStatus
    error_code: str
    request: dict[str, Any]
    usage: dict[str, int]


class ModelRequestPageResponse(MonitoringResourceResponse):
    items: list[ModelRequest]
    page: int
    page_size: int
    total: int
    total_pages: int


class CommandObservation(MonitoringResponseModel):
    sequence: int
    invocation_id: str
    workflow_node_id: str
    attempt: int
    occurred_at: str
    phase: CommandPhase
    error_code: str
    payload: dict[str, Any]


class CommandObservationSequenceResponse(MonitoringResourceResponse):
    items: list[CommandObservation]
    after_sequence: int
    next_after_sequence: int
    limit: int
    remaining: int


class PersistedWorkflowState(MonitoringResponseModel):
    checkpoint_id: str
    checkpoint_ns: str
    created_at: str
    source: str
    step: int | None
    pending_write_count: int
    state: dict[str, Any]


class WorkflowStateResponse(MonitoringResourceResponse):
    state: PersistedWorkflowState | None


class AgentInvocationResponse(MonitoringResourceResponse):
    workflow_node_id: str | None = None
    artifact: dict[str, Any] | None


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

    @router.get(
        prefix + "/runs/{run_id}/graph",
        response_model=MonitoringGraphResponse,
    )
    async def graph(lifecycle_id: str, run_id: str):
        return read(lambda: service.graph(lifecycle_id, run_id))

    @router.get(
        prefix + "/runs/{run_id}/nodes",
        response_model=NodeSummaryPageResponse,
    )
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
        response_model=NodeAttemptPageResponse,
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
        response_model=ProtocolEventSequenceResponse,
    )
    async def protocol_events(
        lifecycle_id: str,
        run_id: str,
        after_sequence: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
        method: str | None = Query(default=None, min_length=1),
        node_id: str | None = Query(default=None, min_length=1),
        invocation_id: str | None = Query(default=None, min_length=1),
    ):
        if invocation_id is not None and node_id is None:
            raise management_error(
                422,
                code="runtime_monitoring_protocol_selector_invalid",
                message_key="errors.runtimeMonitoringProtocolSelectorInvalid",
                message="Select a Node before selecting an invocation.",
            )
        return read(
            lambda: service.protocol_events(
                lifecycle_id,
                run_id,
                after_sequence=after_sequence,
                limit=limit,
                method=method,
                node_id=node_id,
                invocation_id=invocation_id,
            )
        )

    @router.get(
        prefix + "/runs/{run_id}/model-requests",
        response_model=ModelRequestPageResponse,
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
        response_model=CommandObservationSequenceResponse,
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
        response_model=WorkflowStateResponse,
    )
    async def state(lifecycle_id: str, run_id: str):
        return await aread(lambda: service.latest_state(lifecycle_id, run_id))

    @router.get(
        prefix + "/runs/{run_id}/agent-invocations/{invocation_id}",
        response_model=AgentInvocationResponse,
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
    "AgentInvocationResponse",
    "CommandObservationSequenceResponse",
    "ModelRequestPageResponse",
    "MonitoringGraphResponse",
    "MonitoringResourceResponse",
    "MonitoringSnapshotResponse",
    "NodeAttemptPageResponse",
    "NodeSummaryPageResponse",
    "ProtocolEventSequenceResponse",
    "WorkflowStateResponse",
    "build_runtime_monitoring_router",
]
