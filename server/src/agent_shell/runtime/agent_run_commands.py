from __future__ import annotations

from typing import Protocol

from agent_shell.runtime.agent_run_calls import AgentRunHandle, AgentRunSnapshot
from agent_shell.runtime.run_calls import RunCaller


class AgentRunRuntime(Protocol):
    async def start_agent_run(
        self,
        main_agent_id: str,
        input: object,
        *,
        operation_id: str,
        caller: RunCaller,
        thread_id: str | None = None,
    ) -> AgentRunHandle: ...

    async def check_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot: ...

    async def join_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot: ...

    async def cancel_agent_run(
        self,
        thread_id: str,
        run_id: str,
        *,
        caller: RunCaller,
    ) -> AgentRunSnapshot: ...


class AgentRunCommands:
    """Run-scoped facade for independent Main Agent Graph Runs."""

    __slots__ = ("_caller", "_runtime")

    def __init__(self, runtime: AgentRunRuntime, caller: RunCaller) -> None:
        self._runtime = runtime
        self._caller = caller

    def for_caller(self, caller: RunCaller) -> AgentRunCommands:
        return AgentRunCommands(self._runtime, caller)

    async def start(
        self,
        main_agent_id: str,
        input: object,
        *,
        operation_id: str,
        thread_id: str | None = None,
    ) -> AgentRunHandle:
        return await self._runtime.start_agent_run(
            main_agent_id,
            input,
            operation_id=operation_id,
            caller=self._caller,
            thread_id=thread_id,
        )

    async def check(self, thread_id: str, run_id: str) -> AgentRunSnapshot:
        return await self._runtime.check_agent_run(
            thread_id,
            run_id,
            caller=self._caller,
        )

    async def get(self, thread_id: str, run_id: str) -> AgentRunSnapshot:
        return await self.check(thread_id, run_id)

    async def join(self, thread_id: str, run_id: str) -> AgentRunSnapshot:
        return await self._runtime.join_agent_run(
            thread_id,
            run_id,
            caller=self._caller,
        )

    async def cancel(self, thread_id: str, run_id: str) -> AgentRunSnapshot:
        return await self._runtime.cancel_agent_run(
            thread_id,
            run_id,
            caller=self._caller,
        )


__all__ = ["AgentRunCommands", "AgentRunRuntime"]
