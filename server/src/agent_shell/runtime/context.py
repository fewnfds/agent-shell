from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from agent_shell.runtime.background_commands import (
    BackgroundRunCaller,
    BackgroundRunCommands,
    BackgroundRunRuntime,
)


def _detached(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _detached(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_detached(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_detached(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Per-invocation context passed through the Workflow graph.

    Lifecycle-shared input lives in the graph Store. This context contains only
    immutable identity and configuration for the current run or invocation.
    """

    request_id: str = ""
    lifecycle_id: str = ""
    run_id: str = ""
    thread_id: str = ""
    parent_run_id: str = ""
    background_task_id: str = ""
    launcher_id: str = ""
    run_depth: int = 0
    workflow: Mapping[str, Any] = field(default_factory=dict)
    workflow_node_id: str = ""
    agent_id: str = ""
    invocation_id: str = ""
    background_runs: BackgroundRunCommands | None = None

    @classmethod
    def for_run(
        cls,
        *,
        request_id: str,
        lifecycle_id: str,
        run_id: str,
        thread_id: str,
        parent_run_id: str = "",
        background_task_id: str = "",
        launcher_id: str = "",
        run_depth: int = 0,
        workflow: Mapping[str, Any] | None = None,
        background_runtime: BackgroundRunRuntime | None = None,
    ) -> "WorkflowRuntimeContext":
        context = cls(
            request_id=request_id,
            lifecycle_id=lifecycle_id,
            run_id=run_id,
            thread_id=thread_id,
            parent_run_id=parent_run_id,
            background_task_id=background_task_id,
            launcher_id=launcher_id,
            run_depth=run_depth,
            workflow=_detached(deepcopy(dict(workflow or {}))),
        )
        if background_runtime is None:
            return context
        return replace(
            context,
            background_runs=BackgroundRunCommands(
                background_runtime,
                BackgroundRunCaller(
                    request_id=request_id,
                    lifecycle_id=lifecycle_id,
                    run_id=run_id,
                    run_depth=run_depth,
                    workflow=context.workflow,
                ),
            ),
        )

    def for_workflow_node(
        self,
        *,
        workflow_node_id: str,
        invocation_id: str,
    ) -> "WorkflowRuntimeContext":
        """Bind one canvas Node invocation to run-scoped dependencies."""

        background_runs = (
            self.background_runs.for_caller(workflow_node_id)
            if self.background_runs is not None
            else None
        )
        return replace(
            self,
            workflow_node_id=workflow_node_id,
            invocation_id=invocation_id,
            background_runs=background_runs,
        )

    def for_workflow_agent(
        self,
        *,
        workflow_node_id: str,
        agent_id: str,
        invocation_id: str,
    ) -> "WorkflowRuntimeContext":
        """Bind stable canvas Agent identity to a foreground child invocation."""

        return replace(
            self.for_workflow_node(
                workflow_node_id=workflow_node_id,
                invocation_id=invocation_id,
            ),
            agent_id=agent_id,
        )

    def for_background_agent(
        self,
        *,
        agent_id: str,
        invocation_id: str,
    ) -> "WorkflowRuntimeContext":
        """Bind an Agent Run that is not owned by a canvas Agent Node."""

        background_runs = (
            self.background_runs.for_caller(invocation_id)
            if self.background_runs is not None
            else None
        )
        return replace(
            self,
            workflow_node_id="",
            agent_id=agent_id,
            invocation_id=invocation_id,
            background_runs=background_runs,
        )


__all__ = ["WorkflowRuntimeContext"]
