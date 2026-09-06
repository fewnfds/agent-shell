from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent_shell.runtime.errors import AgentRuntimeError


@dataclass(frozen=True, slots=True)
class AsyncSubagentRunTarget:
    """Frozen target settings used when an official async child Run is created."""

    async_subagent_id: str
    main_agent_id: str
    main_agent_name: str
    on_disconnect: Literal["cancel", "continue"]


class AsyncSubagentRunObserver(Protocol):
    """Narrow Lifecycle owner used by the public Agent Middleware hook."""

    def begin_async_subagent_call(self, parent_run_id: str) -> None: ...

    def end_async_subagent_call(self, parent_run_id: str) -> None: ...

    async def record_async_subagent_run(
        self,
        *,
        parent_run_id: str,
        target: AsyncSubagentRunTarget,
        thread_id: str,
        run_id: str,
    ) -> None: ...

    def detach_async_subagent_observation(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> None: ...


class AsyncSubagentRunMiddleware(AgentMiddleware):
    """Associate official Async Subagent Runs with the Shell Lifecycle registry."""

    def __init__(
        self,
        *,
        targets: Mapping[str, AsyncSubagentRunTarget],
        observer: AsyncSubagentRunObserver,
    ) -> None:
        super().__init__()
        self._targets = dict(targets)
        self._observer = observer

    async def _execute_and_observe(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
        parent_run_id: str,
    ) -> ToolMessage | Command[Any]:
        try:
            result = await handler(request)
            if not isinstance(result, Command) or not isinstance(
                result.update, Mapping
            ):
                return result
            tasks = result.update.get("async_tasks")
            if not isinstance(tasks, Mapping):
                return result
            observed: set[str] = set()
            for value in tasks.values():
                if not isinstance(value, Mapping):
                    continue
                child_run_id = str(value.get("run_id") or "")
                thread_id = str(value.get("thread_id") or "")
                agent_name = str(value.get("agent_name") or "")
                target = self._targets.get(agent_name)
                if (
                    target is None
                    or not child_run_id
                    or not thread_id
                    or child_run_id in observed
                ):
                    continue
                observed.add(child_run_id)
                await self._observer.record_async_subagent_run(
                    parent_run_id=parent_run_id,
                    target=target,
                    thread_id=thread_id,
                    run_id=child_run_id,
                )
            return result
        finally:
            self._observer.end_async_subagent_call(parent_run_id)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        tool_name = str(request.tool_call.get("name") or "")
        if tool_name not in {"start_async_task", "update_async_task"}:
            return await handler(request)
        execution_info = request.runtime.execution_info
        parent_run_id = (
            str(execution_info.run_id or "")
            if execution_info is not None
            else ""
        )
        if not parent_run_id:
            return await handler(request)

        self._observer.begin_async_subagent_call(parent_run_id)
        completion = asyncio.create_task(
            self._execute_and_observe(request, handler, parent_run_id),
            name=f"async-subagent-run-observation:{parent_run_id}",
        )
        try:
            return await asyncio.shield(completion)
        except asyncio.CancelledError:
            async def finish_observation() -> None:
                try:
                    await completion
                except BaseException:
                    pass

            self._observer.detach_async_subagent_observation(
                finish_observation(),
                name=f"async-subagent-run-observation:{parent_run_id}",
            )
            raise


def make_async_subagent_run_middleware(
    *,
    references: Sequence[Any],
    observer: AsyncSubagentRunObserver,
) -> AsyncSubagentRunMiddleware:
    targets = {
        reference.name: AsyncSubagentRunTarget(
            async_subagent_id=reference.async_subagent_id,
            main_agent_id=reference.main_agent_id,
            main_agent_name=reference.main_agent_name,
            on_disconnect=reference.on_disconnect,
        )
        for reference in references
    }
    return AsyncSubagentRunMiddleware(targets=targets, observer=observer)


def make_subagent_middleware_override(
    *,
    backend: Any,
    subagents: Sequence[dict[str, Any]],
    task_description: str | None,
    middleware: Sequence[Any],
    state_schema: type | None = None,
) -> Any | None:
    """Build the official same-name replacement."""

    try:
        from deepagents.middleware import SubAgentMiddleware
        from deepagents.middleware._state import private_state_field_names
        from deepagents.middleware.summarization import SummarizationState

        state_schemas = [SummarizationState]
        if state_schema is not None:
            state_schemas.insert(0, state_schema)
        state_schemas.extend(
            candidate_schema
            for item in middleware
            if (
                candidate_schema := getattr(item, "state_schema", None)
            ) is not None
        )
        return SubAgentMiddleware(
            backend=backend,
            subagents=subagents,
            task_description=task_description,
            private_state_keys=private_state_field_names(*state_schemas),
            state_schema=state_schema,
        )
    except Exception as exc:
        raise AgentRuntimeError(
            "subagent_configuration_failed",
            "The selected synchronous Subagent configuration is invalid.",
            status_code=422,
        ) from exc


def make_async_subagent_middleware_override(
    *,
    async_subagents: Sequence[dict[str, Any]],
    system_prompt: str | None,
    description_overrides: dict[str, str | None],
) -> Any:
    """Configure the official AsyncSubAgentMiddleware without copying its tools."""

    try:
        from deepagents.middleware import AsyncSubAgentMiddleware

        replacement = AsyncSubAgentMiddleware(
            async_subagents=list(async_subagents),
            system_prompt=system_prompt,
        )
        agents = "\n".join(
            f"- {item['name']}: {item['description']}"
            for item in async_subagents
        )
        replacement.tools = [
            tool.model_copy(
                update={
                    "description": (
                        override.format(available_agents=agents)
                        if tool.name == "start_async_task"
                        else override
                    )
                }
            )
            if (override := description_overrides.get(tool.name)) is not None
            else tool
            for tool in replacement.tools
        ]
        return replacement
    except Exception as exc:
        raise AgentRuntimeError(
            "async_subagent_configuration_failed",
            "The selected Async Subagent Middleware configuration is invalid.",
            status_code=422,
        ) from exc
