from __future__ import annotations

from dataclasses import dataclass, replace

from agent_shell.runtime.background_commands import (
    BackgroundRunCaller,
    BackgroundRunCommands,
    BackgroundRunRuntime,
)
from agent_shell.runtime.run_identity import WorkflowRunIdentity


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Per-invocation context passed through the Workflow graph.

    Lifecycle-shared input lives in the graph Store. This context contains only
    immutable identity and configuration for the current run or invocation.
    """

    request_id: str = ""
    lifecycle_id: str = ""
    workflow_run_id: str = ""
    checkpoint_thread_id: str | None = None
    parent_workflow_run_id: str = ""
    background_task_id: str = ""
    launcher_id: str = ""
    run_depth: int = 0
    workflow_id: str = ""
    workflow_name: str = ""
    workflow_role: str = ""
    workflow_node_id: str = ""
    agent_profile_id: str = ""
    node_invocation_id: str = ""
    background_runs: BackgroundRunCommands | None = None

    @classmethod
    def for_run(
        cls,
        *,
        identity: WorkflowRunIdentity,
        background_runtime: BackgroundRunRuntime | None = None,
    ) -> "WorkflowRuntimeContext":
        context = cls(
            request_id=identity.request_id,
            lifecycle_id=identity.lifecycle_id,
            workflow_run_id=identity.workflow_run_id,
            checkpoint_thread_id=identity.checkpoint_thread_id,
            parent_workflow_run_id=identity.parent_workflow_run_id,
            background_task_id=identity.background_task_id,
            launcher_id=identity.launcher_id,
            run_depth=identity.run_depth,
            workflow_id=identity.workflow_id,
            workflow_name=identity.workflow_name,
            workflow_role=identity.workflow_role,
        )
        if background_runtime is None:
            return context
        return replace(
            context,
            background_runs=BackgroundRunCommands(
                background_runtime,
                BackgroundRunCaller(
                    request_id=identity.request_id,
                    lifecycle_id=identity.lifecycle_id,
                    workflow_run_id=identity.workflow_run_id,
                    run_depth=identity.run_depth,
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
            node_invocation_id=invocation_id,
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
            agent_profile_id=agent_id,
        )

__all__ = ["WorkflowRuntimeContext"]
