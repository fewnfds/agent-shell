from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from agent_shell.runtime.background_tasks import (
        BackgroundTaskHandle,
        BackgroundTaskSnapshot,
        BackgroundTaskStatus,
    )


@dataclass(frozen=True, slots=True)
class BackgroundRunCaller:
    """Immutable identity captured when commands are bound to one run."""

    request_id: str
    lifecycle_id: str
    workflow_run_id: str
    run_depth: int


class BackgroundRunRuntime(Protocol):
    async def start_background_workflow(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        caller: BackgroundRunCaller,
        shared_vars: Mapping[str, Any],
        workflow_task: Mapping[str, Any] | None = None,
    ) -> BackgroundTaskHandle: ...

    async def check_background_tasks(
        self,
        task_ids: list[str],
        *,
        caller: BackgroundRunCaller,
    ) -> list[BackgroundTaskSnapshot]: ...

    async def list_background_tasks(
        self,
        *,
        caller: BackgroundRunCaller,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]: ...

    async def cancel_background_tasks(
        self,
        task_ids: list[str],
        *,
        caller: BackgroundRunCaller,
    ) -> list[BackgroundTaskSnapshot]: ...


class BackgroundRunCommands:
    """Run-scoped facade shared by nodes, tools, and middleware through Runtime."""

    __slots__ = ("_caller", "_runtime")

    def __init__(
        self,
        runtime: BackgroundRunRuntime,
        caller: BackgroundRunCaller,
    ) -> None:
        self._runtime = runtime
        self._caller = caller

    async def start_workflow(
        self,
        target_workflow_id: str,
        *,
        operation_id: str,
        shared_vars: Mapping[str, Any] | None = None,
        workflow_task: Mapping[str, Any] | None = None,
    ) -> BackgroundTaskHandle:
        return await self._runtime.start_background_workflow(
            target_workflow_id,
            operation_id=operation_id,
            caller=self._caller,
            shared_vars=shared_vars or {},
            workflow_task=workflow_task,
        )

    async def check(self, task_ids: Sequence[str]) -> list[BackgroundTaskSnapshot]:
        return await self._runtime.check_background_tasks(
            list(task_ids),
            caller=self._caller,
        )

    async def list(
        self,
        *,
        statuses: frozenset[BackgroundTaskStatus] | None = None,
    ) -> list[BackgroundTaskSnapshot]:
        return await self._runtime.list_background_tasks(
            caller=self._caller,
            statuses=statuses,
        )

    async def cancel(self, task_ids: Sequence[str]) -> list[BackgroundTaskSnapshot]:
        return await self._runtime.cancel_background_tasks(
            list(task_ids),
            caller=self._caller,
        )


__all__ = ["BackgroundRunCaller", "BackgroundRunCommands", "BackgroundRunRuntime"]
