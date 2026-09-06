from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from agent_shell.runtime.agent_run_commands import AgentRunCommands, AgentRunRuntime
from agent_shell.runtime.run_calls import RunCaller
from agent_shell.runtime.workflow_run_commands import WorkflowRunCommands, WorkflowRunRuntime
from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity
from agent_shell.runtime.mcp import McpCommands


@dataclass(frozen=True, slots=True)
class WorkflowRunContext:
    """JSON-compatible context accepted by the public Workflow graph."""

    request_id: str = ""
    lifecycle_id: str = ""
    caller_run_id: str = ""
    operation_id: str = ""


@dataclass(frozen=True, slots=True)
class AgentRunContext:
    """JSON-compatible context accepted by the Main Agent root graph."""

    request_id: str = ""
    lifecycle_id: str = ""
    caller_run_id: str = ""
    operation_id: str = ""


@dataclass(frozen=True, slots=True)
class AgentRuntimeContext(AgentRunContext):
    """Execution dependencies visible to Main Agent middleware and tools."""

    run_id: str = ""
    main_agent_id: str = ""

    @classmethod
    def for_run(cls, identity: AgentRunIdentity) -> "AgentRuntimeContext":
        return cls(
            request_id=identity.request_id,
            lifecycle_id=identity.lifecycle_id,
            caller_run_id=identity.caller_run_id,
            operation_id=identity.operation_id,
            run_id=identity.run_id,
            main_agent_id=identity.main_agent_id,
        )


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext(WorkflowRunContext):
    """Execution-only dependencies passed to consumers inside Workflow nodes.

    LangGraph execution identity lives in ``Runtime.execution_info``. This
    context carries only Shell product scope and capabilities that graph
    consumers need through LangGraph's dependency-injection boundary.
    """

    run_id: str = ""
    workflow_id: str = ""
    workflow_node_id: str = ""
    node_invocation_id: str = ""
    agent_runs: AgentRunCommands | None = None
    workflow_runs: WorkflowRunCommands | None = None
    mcp: McpCommands | None = None
    _mcp_commands_by_node: Mapping[str, McpCommands] | None = None

    def run_context(self) -> WorkflowRunContext:
        return WorkflowRunContext(
            request_id=self.request_id,
            lifecycle_id=self.lifecycle_id,
            caller_run_id=self.caller_run_id,
            operation_id=self.operation_id,
        )

    @classmethod
    def for_run(
        cls,
        *,
        identity: WorkflowRunIdentity,
        agent_run_runtime: AgentRunRuntime | None = None,
        workflow_run_runtime: WorkflowRunRuntime | None = None,
        mcp_commands_by_node: Mapping[str, McpCommands] | None = None,
    ) -> "WorkflowRuntimeContext":
        context = cls(
            request_id=identity.request_id,
            lifecycle_id=identity.lifecycle_id,
            run_id=identity.run_id,
            workflow_id=identity.workflow_id,
            caller_run_id=identity.caller_run_id,
            operation_id=identity.operation_id,
        )
        return context.with_runtime_bindings(
            agent_run_runtime=agent_run_runtime,
            workflow_run_runtime=workflow_run_runtime,
            mcp_commands_by_node=mcp_commands_by_node,
        )

    def with_runtime_bindings(
        self,
        *,
        agent_run_runtime: AgentRunRuntime | None = None,
        workflow_run_runtime: WorkflowRunRuntime | None = None,
        mcp_commands_by_node: Mapping[str, McpCommands] | None = None,
    ) -> "WorkflowRuntimeContext":
        """Attach execution-only capabilities without exposing them as JSON context."""

        return replace(
            self,
            agent_runs=(
                AgentRunCommands(
                    agent_run_runtime,
                    RunCaller(
                        request_id=self.request_id,
                        lifecycle_id=self.lifecycle_id,
                        run_id=self.run_id,
                    ),
                )
                if agent_run_runtime is not None
                else None
            ),
            workflow_runs=(
                WorkflowRunCommands(
                    workflow_run_runtime,
                    RunCaller(
                        request_id=self.request_id,
                        lifecycle_id=self.lifecycle_id,
                        run_id=self.run_id,
                    ),
                )
                if workflow_run_runtime is not None
                else None
            ),
            _mcp_commands_by_node=mcp_commands_by_node,
        )

    def for_server_run(self, run_id: str) -> "WorkflowRuntimeContext":
        """Bind identity-dependent capabilities to one official Server Run."""

        return replace(
            self,
            run_id=run_id,
            agent_runs=(
                self.agent_runs.for_caller(
                    RunCaller(
                        request_id=self.request_id,
                        lifecycle_id=self.lifecycle_id,
                        run_id=run_id,
                    )
                )
                if self.agent_runs is not None
                else None
            ),
            workflow_runs=(
                self.workflow_runs.for_caller(
                    RunCaller(
                        request_id=self.request_id,
                        lifecycle_id=self.lifecycle_id,
                        run_id=run_id,
                    )
                )
                if self.workflow_runs is not None
                else None
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

__all__ = [
    "AgentRunContext",
    "AgentRuntimeContext",
    "WorkflowRunContext",
    "WorkflowRuntimeContext",
]
