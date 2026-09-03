from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal, TypeVar

from agent_shell.runtime.workflow_checkpoints import WorkflowCheckpointService
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.runtime_monitoring_queries import (
    RuntimeMonitoringQueryStore,
    ScopeKind,
)


Availability = Literal[
    "not_enabled",
    "unavailable",
    "capturing",
    "available",
    "partial",
    "pending",
    "not_applicable",
]
_ReadResult = TypeVar("_ReadResult")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MonitoringReadError(RuntimeError):
    pass


class MonitoringReadUnavailable(MonitoringReadError):
    pass


class MonitoringLifecycleNotFound(MonitoringReadError):
    pass


class MonitoringRunNotFound(MonitoringReadError):
    pass


class MonitoringWorkflowNotFound(MonitoringReadError):
    pass


class MonitoringNodeNotFound(MonitoringReadError):
    pass


class MonitoringInvocationNotFound(MonitoringReadError):
    pass


class MonitoringCaptureDisabled(MonitoringReadError):
    pass


def _partition_availability(
    runs: list[dict[str, object]],
    partition: str,
) -> Availability:
    if not runs:
        return "not_applicable"
    statuses: list[str] = []
    missing = False
    for run in runs:
        monitoring = run.get("monitoring")
        if not isinstance(monitoring, dict):
            missing = True
            continue
        statuses.append(str(monitoring[partition]))
    if missing or not statuses or "partial" in statuses:
        return "partial"
    if "capturing" in statuses:
        return "capturing"
    if all(status == "not_applicable" for status in statuses):
        return "not_applicable"
    return "available"


class MonitoringReadService:
    """Compose monitoring views while preserving each persistence owner."""

    def __init__(
        self,
        database: SQLiteDatabase,
        queries: RuntimeMonitoringQueryStore,
        lifecycle: WorkflowLifecycleService,
        checkpoints: WorkflowCheckpointService,
    ) -> None:
        self._database = database
        self._queries = queries
        self._lifecycle = lifecycle
        self._checkpoints = checkpoints

    async def application_query(
        self,
        call: Callable[[], _ReadResult],
    ) -> _ReadResult:
        """Run one composed application-database view off the event loop."""

        return await self._database.run(call)

    def _require_lifecycle(self, lifecycle_id: str) -> dict[str, object]:
        try:
            record = self._queries.lifecycle(lifecycle_id)
        except Exception as exc:
            raise MonitoringReadUnavailable(
                "The runtime registry could not be read."
            ) from exc
        if record is None:
            raise MonitoringLifecycleNotFound(lifecycle_id)
        if not record["monitoring_capture_enabled"]:
            raise MonitoringCaptureDisabled(lifecycle_id)
        return record

    def _require_run(
        self,
        lifecycle_id: str,
        run_id: str,
    ) -> dict[str, object]:
        self._require_lifecycle(lifecycle_id)
        try:
            run = self._queries.run(lifecycle_id, run_id)
        except Exception as exc:
            raise MonitoringReadUnavailable(
                "The Workflow Run registry could not be read."
            ) from exc
        if run is None:
            raise MonitoringRunNotFound(run_id)
        return run

    @staticmethod
    def _resource(
        availability: Availability,
        **content: object,
    ) -> dict[str, object]:
        return {
            "availability": availability,
            "read_at": _now(),
            **content,
        }

    def snapshot(
        self,
        lifecycle_id: str,
        *,
        scope: ScopeKind,
        selector_id: str | None,
    ) -> dict[str, object]:
        lifecycle = self._require_lifecycle(lifecycle_id)
        if scope == "run":
            if not selector_id:
                raise ValueError("run_id is required for Run scope")
            self._require_run(lifecycle_id, selector_id)
        elif scope == "workflow":
            if not selector_id:
                raise ValueError("workflow_id is required for Workflow scope")
            try:
                exists = self._queries.workflow_exists(lifecycle_id, selector_id)
            except Exception as exc:
                raise MonitoringReadUnavailable(
                    "The Workflow scope could not be read."
                ) from exc
            if not exists:
                raise MonitoringWorkflowNotFound(selector_id)
        elif scope != "lifecycle":
            raise ValueError("unknown monitoring scope")
        try:
            runs = self._queries.scope_runs(
                lifecycle_id,
                kind=scope,
                selector_id=selector_id,
            )
        except Exception as exc:
            raise MonitoringReadUnavailable(
                "The runtime monitoring snapshot could not be read."
            ) from exc
        node_counts_available = True
        try:
            node_attempt_status_counts = (
                self._queries.scope_node_attempt_status_counts(
                    lifecycle_id,
                    kind=scope,
                    selector_id=selector_id,
                )
            )
        except Exception:
            node_counts_available = False
            node_attempt_status_counts = {}

        run_ids = {str(run["run_id"]) for run in runs}
        roots: list[str] = []
        orphans: list[str] = []
        relationships: list[dict[str, str]] = []
        for run in runs:
            run_id = str(run["run_id"])
            raw_parent = run.get("parent_run_id")
            parent_id = str(raw_parent) if raw_parent else ""
            if parent_id and parent_id in run_ids:
                relationships.append(
                    {"parent_run_id": parent_id, "child_run_id": run_id}
                )
            else:
                roots.append(run_id)
                if not parent_id and int(run.get("run_depth", 0)) > 0:
                    orphans.append(run_id)

        run_status_counts = Counter(str(run["status"]) for run in runs)
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for run in runs:
            run_usage = run["usage"]
            assert isinstance(run_usage, dict)
            for name in usage:
                usage[name] += int(run_usage[name])
        partition_availability = {
            name: _partition_availability(runs, name)
            for name in ("graph", "node", "protocol", "model", "command")
        }
        if not node_counts_available:
            partition_availability["node"] = "unavailable"
        return {
            "selector": {
                "scope": scope,
                "id": selector_id,
            },
            "read_at": _now(),
            "lifecycle": lifecycle,
            "summary": {
                "run_count": len(runs),
                "active_run_count": (
                    run_status_counts["pending"] + run_status_counts["running"]
                ),
                "failed_run_count": (
                    run_status_counts["failed"]
                    + run_status_counts["interrupted"]
                ),
                "run_status_counts": dict(sorted(run_status_counts.items())),
                "node_attempt_status_counts": node_attempt_status_counts,
                "usage": usage,
                "partition_availability": partition_availability,
            },
            "runs": runs,
            "forest": {
                "root_run_ids": roots,
                "relationships": relationships,
                "orphan_run_ids": orphans,
                "relationship_availability": (
                    "partial" if orphans else "available"
                ),
            },
        }

    def graph(self, lifecycle_id: str, run_id: str) -> dict[str, object]:
        run = self._require_run(lifecycle_id, run_id)
        availability = _partition_availability([run], "graph")
        try:
            graph = self._queries.graph(lifecycle_id, run_id)
        except Exception:
            return self._resource("unavailable", graph=None)
        if graph is None:
            if availability == "available":
                availability = "partial"
            return self._resource(availability, graph=None)
        return self._resource(availability, graph=graph)

    def node_summaries(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> dict[str, object]:
        run = self._require_run(lifecycle_id, run_id)
        availability = _partition_availability([run], "node")
        try:
            result = self._queries.node_summaries(
                lifecycle_id,
                run_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        except Exception:
            return self._resource(
                "unavailable",
                items=[],
                page=page,
                page_size=page_size,
                total=0,
                total_pages=1,
            )
        return self._resource(availability, **result)

    def node_attempts(
        self,
        lifecycle_id: str,
        run_id: str,
        node_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> dict[str, object]:
        run = self._require_run(lifecycle_id, run_id)
        graph_response = self.graph(lifecycle_id, run_id)
        graph = graph_response.get("graph")
        if isinstance(graph, dict):
            document = graph.get("document")
            definition = (
                document.get("definition") if isinstance(document, dict) else None
            )
            nodes = (
                definition.get("nodes") if isinstance(definition, dict) else None
            )
            if isinstance(nodes, list) and not any(
                isinstance(node, dict) and node.get("id") == node_id
                for node in nodes
            ):
                raise MonitoringNodeNotFound(node_id)
        availability = _partition_availability([run], "node")
        try:
            result = self._queries.node_attempts(
                lifecycle_id,
                run_id,
                node_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        except Exception:
            return self._resource(
                "unavailable",
                items=[],
                page=page,
                page_size=page_size,
                total=0,
                total_pages=1,
            )
        return self._resource(availability, **result)

    def protocol_events(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
        method: str | None,
        node_id: str | None = None,
        invocation_id: str | None = None,
    ) -> dict[str, object]:
        if invocation_id is not None and node_id is None:
            raise ValueError("node_id is required when invocation_id is selected")
        return self._sequence_resource(
            lifecycle_id,
            run_id,
            partition="protocol",
            empty={
                "items": [],
                "after_sequence": after_sequence,
                "next_after_sequence": after_sequence,
                "limit": limit,
                "remaining": 0,
            },
            read=lambda: self._queries.protocol_events(
                lifecycle_id,
                run_id,
                after_sequence=after_sequence,
                limit=limit,
                method=method,
                node_id=node_id,
                invocation_id=invocation_id,
            ),
        )

    def model_requests(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> dict[str, object]:
        run = self._require_run(lifecycle_id, run_id)
        availability = _partition_availability([run], "model")
        try:
            result = self._queries.model_requests(
                lifecycle_id,
                run_id,
                page=page,
                page_size=page_size,
                status=status,
            )
        except Exception:
            return self._resource(
                "unavailable",
                items=[],
                page=page,
                page_size=page_size,
                total=0,
                total_pages=1,
            )
        return self._resource(availability, **result)

    def command_observations(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
        node_id: str | None,
        phase: str | None,
    ) -> dict[str, object]:
        return self._sequence_resource(
            lifecycle_id,
            run_id,
            partition="command",
            empty={
                "items": [],
                "after_sequence": after_sequence,
                "next_after_sequence": after_sequence,
                "limit": limit,
                "remaining": 0,
            },
            read=lambda: self._queries.command_observations(
                lifecycle_id,
                run_id,
                after_sequence=after_sequence,
                limit=limit,
                node_id=node_id,
                phase=phase,
            ),
        )

    def _sequence_resource(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        partition: str,
        empty: dict[str, object],
        read,
    ) -> dict[str, object]:
        run = self._require_run(lifecycle_id, run_id)
        availability = _partition_availability([run], partition)
        try:
            result = read()
        except Exception:
            return self._resource("unavailable", **empty)
        return self._resource(availability, **result)

    async def latest_state(
        self,
        lifecycle_id: str,
        run_id: str,
    ) -> dict[str, object]:
        run = await self.application_query(
            lambda: self._require_run(lifecycle_id, run_id)
        )
        thread_id = run.get("checkpoint_thread_id")
        if not thread_id:
            return self._resource("not_enabled", state=None)
        try:
            state = await self._checkpoints.latest_state(str(thread_id))
        except Exception:
            return self._resource("unavailable", state=None)
        if state is None:
            availability: Availability = (
                "pending"
                if run["status"] in {"pending", "running"}
                else "partial"
            )
            return self._resource(availability, state=None)
        return self._resource("available", state=state)

    async def agent_invocation(
        self,
        lifecycle_id: str,
        run_id: str,
        invocation_id: str,
    ) -> dict[str, object]:
        await self.application_query(
            lambda: self._require_run(lifecycle_id, run_id)
        )
        try:
            attempts, graph = await self.application_query(
                lambda: (
                    self._queries.invocation_attempts(
                        lifecycle_id,
                        run_id,
                        invocation_id,
                    ),
                    self._queries.graph(lifecycle_id, run_id),
                )
            )
        except Exception:
            return self._resource("unavailable", artifact=None)
        if not attempts:
            raise MonitoringInvocationNotFound(invocation_id)
        node_ids = {str(attempt["workflow_node_id"]) for attempt in attempts}
        if len(node_ids) != 1:
            return self._resource("partial", artifact=None)
        node_id = next(iter(node_ids))
        if graph is None:
            return self._resource("partial", artifact=None)
        document = graph.get("document")
        definition = (
            document.get("definition") if isinstance(document, dict) else None
        )
        nodes = definition.get("nodes") if isinstance(definition, dict) else None
        node = next(
            (
                item
                for item in nodes or ()
                if isinstance(item, dict) and item.get("id") == node_id
            ),
            None,
        )
        if not isinstance(node, dict) or node.get("type") != "agent":
            return self._resource("not_applicable", artifact=None)
        if not any(attempt["status"] == "completed" for attempt in attempts):
            availability: Availability = (
                "pending"
                if any(attempt["status"] == "running" for attempt in attempts)
                else "not_applicable"
            )
            return self._resource(availability, artifact=None)
        try:
            artifact = await self._lifecycle.agent_invocation_artifact(
                lifecycle_id,
                run_id,
                invocation_id,
            )
        except Exception:
            return self._resource("unavailable", artifact=None)
        if artifact is None:
            return self._resource("partial", artifact=None)
        node_config = node.get("config")
        expected_agent_id = (
            node_config.get("main_agent_id")
            if isinstance(node_config, dict)
            else None
        )
        if (
            not isinstance(artifact, dict)
            or artifact.get("invocation_id") != invocation_id
            or artifact.get("workflow_node_id") != node_id
            or artifact.get("workflow_id") != graph.get("workflow_id")
            or artifact.get("agent_id") != expected_agent_id
        ):
            return self._resource("partial", artifact=None)
        return self._resource(
            "available",
            workflow_node_id=node_id,
            artifact=artifact,
        )


__all__ = [
    "Availability",
    "MonitoringCaptureDisabled",
    "MonitoringLifecycleNotFound",
    "MonitoringInvocationNotFound",
    "MonitoringNodeNotFound",
    "MonitoringReadError",
    "MonitoringReadService",
    "MonitoringReadUnavailable",
    "MonitoringRunNotFound",
    "MonitoringWorkflowNotFound",
]
