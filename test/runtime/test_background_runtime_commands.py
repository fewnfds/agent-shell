from __future__ import annotations

import asyncio

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from agent_shell.command import run_command
from agent_shell.runtime.background_commands import BackgroundRunCaller
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.task_dispatcher import run_task_dispatcher


class _CommandRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, BackgroundRunCaller]] = []
        self.starts: list[tuple[str, str, BackgroundRunCaller]] = []

    async def list_background_tasks(self, *, caller, statuses=None):
        self.calls.append(("list", caller))
        return []

    async def check_background_tasks(self, task_ids, *, caller):
        self.calls.append(("check", caller))
        return []

    async def cancel_background_tasks(self, task_ids, *, caller):
        self.calls.append(("cancel", caller))
        return []

    async def start_background_agent(self, target_agent_id, **kwargs):
        self.starts.append((target_agent_id, kwargs["operation_id"], kwargs["caller"]))
        return object()

    async def start_background_workflow(self, target_workflow_id, **kwargs):
        raise AssertionError("not used by this access test")


def _context(service: _CommandRuntime) -> WorkflowRuntimeContext:
    return WorkflowRuntimeContext.for_run(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        run_id="run-1",
        thread_id="thread-1",
        workflow={"id": "workflow-1"},
        background_runtime=service,
    )


def test_command_and_dispatcher_receive_the_official_runtime_commands() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        official_runtime = Runtime(context=_context(service))
        seen = []

        async def command(state, runtime):
            seen.append(runtime)
            assert runtime.context.background_runs is not None
            await runtime.context.background_runs.list()
            return {"activate": [], "update": {}}

        async def dispatch(state, runtime):
            seen.append(runtime)
            assert runtime.context.background_runs is not None
            await runtime.context.background_runs.check(["task-1"])
            return {
                "tasks": [
                    {
                        "task_id": "task-1",
                        "dispatch_key": "work",
                        "payload": {},
                    }
                ],
                "update": {},
            }

        await run_command(
            command,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=official_runtime,
            allowed_branches=set(),
        )
        await run_task_dispatcher(
            dispatch,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=official_runtime,
            allowed_dispatch_keys={"work"},
        )

        assert seen == [official_runtime, official_runtime]
        assert [name for name, _caller in service.calls] == ["list", "check"]
        assert all(caller.run_id == "run-1" for _name, caller in service.calls)

    asyncio.run(scenario())


def test_command_can_start_background_agent_and_end_without_a_target() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        official_runtime = Runtime(context=_context(service))

        async def command(state, runtime):
            assert runtime.context.background_runs is not None
            await runtime.context.background_runs.start_agent(
                "agent-1",
                operation_id="publish-review",
                shared_vars={"task_id": "task-1"},
            )
            return {"activate": [], "update": {"shared_vars": {"published": True}}}

        result = await run_command(
            command,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=official_runtime,
            allowed_branches=set(),
        )

        assert result.activate == []
        assert result.update == {"shared_vars": {"published": True}}
        assert service.starts[0][:2] == ("agent-1", "publish-review")
        assert service.starts[0][2].run_id == "run-1"

    asyncio.run(scenario())


def test_tool_and_middleware_access_commands_through_official_runtime() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        context = _context(service)
        seen = []

        @tool
        async def background_count(
            runtime: ToolRuntime[WorkflowRuntimeContext],
        ) -> str:
            """Return the number of background runs in this lifecycle."""

            seen.append(runtime.context.background_runs)
            assert runtime.context.background_runs is not None
            return str(len(await runtime.context.background_runs.list()))

        graph = (
            StateGraph(MessagesState, context_schema=WorkflowRuntimeContext)
            .add_node("tools", ToolNode([background_count]))
            .add_edge(START, "tools")
            .add_edge("tools", END)
            .compile()
        )
        result = await graph.ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "background_count",
                                "args": {},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            },
            context=context,
        )

        class ProbeMiddleware(AgentMiddleware):
            async def abefore_agent(self, state, runtime):
                seen.append(runtime.context.background_runs)

        await ProbeMiddleware().abefore_agent({}, Runtime(context=context))

        assert result["messages"][-1].content == "0"
        assert seen == [context.background_runs, context.background_runs]

    asyncio.run(scenario())


def test_background_agent_has_its_own_identity_and_command_caller() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        context = WorkflowRuntimeContext.for_run(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            run_id="child-run-1",
            thread_id="child-thread-1",
            parent_run_id="parent-run-1",
            background_task_id="task-1",
            launcher_id="router-1",
            run_depth=1,
            workflow={"id": "workflow-1"},
            background_runtime=service,
        ).for_background_agent(
            agent_id="agent-1",
            invocation_id="task-1",
        )

        assert context.launcher_id == "router-1"
        assert context.background_task_id == "task-1"
        assert context.agent_id == "agent-1"
        assert context.workflow_node_id == ""
        assert context.invocation_id == "task-1"
        assert context.background_runs is not None

        await context.background_runs.list()

        assert service.calls == [("list", service.calls[0][1])]
        caller = service.calls[0][1]
        assert caller.run_id == "child-run-1"
        assert caller.caller_id == "task-1"

    asyncio.run(scenario())
