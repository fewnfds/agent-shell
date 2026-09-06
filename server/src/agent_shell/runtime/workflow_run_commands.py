from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from agent_shell.runtime.run_calls import RunCaller, RunStatus
from agent_shell.runtime.workflow_run_calls import (
    WorkflowRunHandle,
    WorkflowRunSnapshot,
)


class WorkflowRunRuntime(Protocol):
    async def start_workflow_run(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        caller: RunCaller,
        shared_vars: Mapping[str, Any],
    ) -> WorkflowRunHandle: ...

    async def check_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]: ...

    async def list_workflow_runs(
        self,
        *,
        caller: RunCaller,
        statuses: frozenset[RunStatus] | None = None,
    ) -> list[WorkflowRunSnapshot]: ...

    async def join_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]: ...

    async def cancel_workflow_runs(
        self,
        run_ids: list[str],
        *,
        caller: RunCaller,
    ) -> list[WorkflowRunSnapshot]: ...


class WorkflowRunCommands:
    """Run-scoped official Workflow Run facade for nodes, tools and middleware."""

    __slots__ = ("_caller", "_runtime")

    def __init__(
        self,
        runtime: WorkflowRunRuntime,
        caller: RunCaller,
    ) -> None:
        self._runtime = runtime
        self._caller = caller

    def for_caller(self, caller: RunCaller) -> WorkflowRunCommands:
        """Bind the same Run command runtime to the current official caller."""

        return WorkflowRunCommands(self._runtime, caller)

    async def start_workflow(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        shared_vars: Mapping[str, Any] | None = None,
    ) -> WorkflowRunHandle:
        return await self._runtime.start_workflow_run(
            target_workflow_id,
            operation_id=operation_id,
            caller=self._caller,
            shared_vars=shared_vars or {},
        )

    async def check(self, run_ids: Sequence[str]) -> list[WorkflowRunSnapshot]:
        return await self._runtime.check_workflow_runs(
            list(run_ids),
            caller=self._caller,
        )

    async def list(
        self,
        *,
        statuses: frozenset[RunStatus] | None = None,
    ) -> list[WorkflowRunSnapshot]:
        return await self._runtime.list_workflow_runs(
            caller=self._caller,
            statuses=statuses,
        )

    async def join(self, run_ids: Sequence[str]) -> list[WorkflowRunSnapshot]:
        return await self._runtime.join_workflow_runs(
            list(run_ids),
            caller=self._caller,
        )

    async def cancel(self, run_ids: Sequence[str]) -> list[WorkflowRunSnapshot]:
        return await self._runtime.cancel_workflow_runs(
            list(run_ids),
            caller=self._caller,
        )


__all__ = ["WorkflowRunCommands", "WorkflowRunRuntime"]
