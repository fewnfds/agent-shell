from __future__ import annotations

import asyncio

from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from agent_shell.command import run_command
from agent_shell.runtime.agent_run_calls import AgentRunHandle
from agent_shell.runtime.run_calls import RunCaller
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity


class _CommandRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RunCaller]] = []
        self.starts: list[tuple[str, str, RunCaller]] = []
        self.agent_starts: list[tuple[str, object, str, RunCaller]] = []

    async def list_workflow_runs(self, *, caller, statuses=None):
        self.calls.append(("list", caller))
        return []

    async def check_workflow_runs(self, run_ids, *, caller):
        self.calls.append(("check", caller))
        return []

    async def cancel_workflow_runs(self, run_ids, *, caller):
        self.calls.append(("cancel", caller))
        return []

    async def join_workflow_runs(self, run_ids, *, caller):
        self.calls.append(("join", caller))
        return []

    async def start_workflow_run(self, target_workflow_id, **kwargs):
        self.starts.append(
            (target_workflow_id, kwargs["operation_id"], kwargs["caller"])
        )
        return object()

    async def start_agent_run(self, main_agent_id, input, **kwargs):
        self.agent_starts.append(
            (main_agent_id, input, kwargs["operation_id"], kwargs["caller"])
        )
        return AgentRunHandle(
            operation_id=kwargs["operation_id"],
            main_agent_id=main_agent_id,
            assistant_id="assistant-agent",
            thread_id="thread-agent",
            run_id="run-agent",
            status="pending",
            checkpoint_mode="enabled",
        )


def _context(service: _CommandRuntime) -> WorkflowRuntimeContext:
    return WorkflowRuntimeContext.for_run(
        identity=WorkflowRunIdentity(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            run_id="run-1",
            workflow_id="workflow-1",
            workflow_name="Workflow",
        ),
        agent_run_runtime=service,
        workflow_run_runtime=service,
    )


def test_commands_receive_the_official_runtime_commands() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        official_runtime = Runtime(context=_context(service))
        seen = []

        async def command(state, runtime):
            seen.append(runtime)
            assert runtime.context.workflow_runs is not None
            await runtime.context.workflow_runs.list()
            return {"activate": [], "update": {}}

        async def dispatching_command(state, runtime):
            seen.append(runtime)
            assert runtime.context.workflow_runs is not None
            await runtime.context.workflow_runs.check(["run-2"])
            return {
                "dispatch": [
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
        await run_command(
            dispatching_command,
            state={"shared_vars": {}, "agent_invocations": {}, "files": {}},
            runtime=official_runtime,
            allowed_branches=set(),
            allowed_dispatch_keys={"work"},
        )

        assert seen == [official_runtime, official_runtime]
        assert [name for name, _caller in service.calls] == ["list", "check"]
        assert all(
            caller.run_id == "run-1" for _name, caller in service.calls
        )

    asyncio.run(scenario())


def test_command_can_start_workflow_run_and_end_without_a_target() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        official_runtime = Runtime(context=_context(service))

        async def command(state, runtime):
            assert runtime.context.workflow_runs is not None
            assert runtime.context.agent_runs is not None
            await runtime.context.workflow_runs.start_workflow(
                "workflow-1",
                operation_id="publish-review",
                shared_vars={"task_id": "task-1"},
            )
            await runtime.context.agent_runs.start(
                "agent-1",
                [{"role": "user", "content": "review"}],
                operation_id="agent-review",
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
        assert service.starts[0][:2] == ("workflow-1", "publish-review")
        assert service.starts[0][2].run_id == "run-1"
        assert service.agent_starts[0][:3] == (
            "agent-1",
            [{"role": "user", "content": "review"}],
            "agent-review",
        )
        assert service.agent_starts[0][3].run_id == "run-1"

    asyncio.run(scenario())


def test_tool_and_middleware_access_commands_through_official_runtime() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        context = _context(service)
        seen = []

        @tool
        async def workflow_run_count(
            runtime: ToolRuntime[WorkflowRuntimeContext],
        ) -> str:
            """Return the number of called Workflow Runs in this Lifecycle."""

            seen.append(runtime.context.workflow_runs)
            assert runtime.context.workflow_runs is not None
            return str(len(await runtime.context.workflow_runs.list()))

        graph = (
            StateGraph(MessagesState, context_schema=WorkflowRuntimeContext)
            .add_node("tools", ToolNode([workflow_run_count]))
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
                                "name": "workflow_run_count",
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
                seen.append(runtime.context.workflow_runs)

        await ProbeMiddleware().abefore_agent({}, Runtime(context=context))

        assert result["messages"][-1].content == "0"
        assert seen == [context.workflow_runs, context.workflow_runs]

    asyncio.run(scenario())


def test_spawned_workflow_has_its_own_identity_and_command_caller() -> None:
    async def scenario() -> None:
        service = _CommandRuntime()
        context = WorkflowRuntimeContext.for_run(
            identity=WorkflowRunIdentity(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
                run_id="spawned-run-1",
                workflow_id="workflow-1",
                workflow_name="Spawned Workflow",
                caller_run_id="caller-run-1",
                operation_id="operation-1",
            ),
            workflow_run_runtime=service,
        ).for_workflow_node(
            workflow_node_id="command-1",
            node_invocation_id="command-invocation-1",
        )

        assert context.agent_profile_id == ""
        assert context.workflow_node_id == "command-1"
        assert context.node_invocation_id == "command-invocation-1"
        assert context.workflow_runs is not None

        await context.workflow_runs.list()

        assert service.calls == [("list", service.calls[0][1])]
        caller = service.calls[0][1]
        assert caller.run_id == "spawned-run-1"
        assert caller.lifecycle_id == "lifecycle-1"

    asyncio.run(scenario())
