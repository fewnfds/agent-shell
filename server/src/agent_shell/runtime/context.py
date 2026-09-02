from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from agent_shell.runtime.background_commands import (
    BackgroundRunCaller,
    BackgroundRunCommands,
    BackgroundRunRuntime,
)
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.mcp import McpCommands


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Shell dependencies passed to consumers inside the Workflow graph.

    LangGraph execution identity lives in ``Runtime.execution_info``. This
    context carries only Shell product scope and capabilities that graph
    consumers need through LangGraph's dependency-injection boundary.
    """

    lifecycle_id: str = ""
    workflow_run_id: str = ""
    workflow_id: str = ""
    workflow_node_id: str = ""
    agent_profile_id: str = ""
    node_invocation_id: str = ""
    background_runs: BackgroundRunCommands | None = None
    mcp: McpCommands | None = None
    _mcp_commands_by_node: Mapping[str, McpCommands] | None = None

    @classmethod
    def for_run(
        cls,
        *,
        identity: WorkflowRunIdentity,
        background_runtime: BackgroundRunRuntime | None = None,
        mcp_commands_by_node: Mapping[str, McpCommands] | None = None,
    ) -> "WorkflowRuntimeContext":
        context = cls(
            lifecycle_id=identity.lifecycle_id,
            workflow_run_id=identity.workflow_run_id,
            workflow_id=identity.workflow_id,
            _mcp_commands_by_node=mcp_commands_by_node,
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
        node_invocation_id: str,
    ) -> "WorkflowRuntimeContext":
        """Bind one canvas Node invocation to run-scoped dependencies."""

        return replace(
            self,
            workflow_node_id=workflow_node_id,
            node_invocation_id=node_invocation_id,
            mcp=(
                self._mcp_commands_by_node.get(workflow_node_id)
                if self._mcp_commands_by_node is not None
                else None
            ),
        )

    def for_workflow_agent(
        self,
        *,
        workflow_node_id: str,
        agent_profile_id: str,
        node_invocation_id: str,
    ) -> "WorkflowRuntimeContext":
        """Bind stable canvas Agent identity to a foreground child invocation."""

        return replace(
            self.for_workflow_node(
                workflow_node_id=workflow_node_id,
                node_invocation_id=node_invocation_id,
            ),
            agent_profile_id=agent_profile_id,
            mcp=None,
        )

__all__ = ["WorkflowRuntimeContext"]
