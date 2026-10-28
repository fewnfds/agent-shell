from __future__ import annotations

import asyncio
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType, SimpleNamespace

from langgraph.runtime import ExecutionInfo, Runtime
import pytest

from agent_shell.command import run_command
from agent_shell.runtime.agent_run_calls import AgentRunHandle, AgentRunSnapshot
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.state import (
    WORKFLOW_STATE_CHANNEL,
    wrap_workflow_state_update,
)
from agent_shell.runtime.workflow_run_calls import WorkflowRunHandle, WorkflowRunSnapshot


REPOSITORY = Path(__file__).parents[2]
EXAMPLES = REPOSITORY / "examples" / "workflow-components" / "command"


def _load_example(key: str) -> ModuleType:
    path = EXAMPLES / key / "main.py"
    spec = importlib.util.spec_from_file_location(
        f"agent_shell_command_example_{key.replace('-', '_')}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _command(key: str):
    command = _load_example(key).create_command()
    assert inspect.iscoroutinefunction(command)
    assert list(inspect.signature(command).parameters) == ["state", "runtime"]
    return command


def test_state_routing_example_reads_updates_and_routes_by_canvas_node_id() -> None:
    result = asyncio.run(
        run_command(
            _command("state-routing-command"),
            state=wrap_workflow_state_update(
                {
                    "items": [
                        {"id": "one", "requires_review": True},
                        {"id": "two", "requires_review": False},
                    ],
                    "review_target_node_id": "manual-review",
                    "complete_target_node_id": "publish",
                    "preserved": True,
                }
            ),
            runtime=Runtime(context=WorkflowRuntimeContext()),
            target_map={"manual-review": "manual-review", "publish": "publish"},
        )
    )

    assert result.goto == "manual-review"
    assert result.update == {
        WORKFLOW_STATE_CHANNEL: {
            "item_count": 2,
            "review_item_count": 1,
            "selected_target_node_id": "manual-review",
        }
    }


def test_runtime_context_example_projects_shell_and_langgraph_identity() -> None:
    context = WorkflowRuntimeContext(
        request_id="request-1",
        lifecycle_id="lifecycle-1",
        caller_run_id="caller-run-1",
        operation_id="operation-1",
        run_id="shell-run-1",
        workflow_id="workflow-1",
        workflow_node_id="inspect-runtime",
        node_invocation_id="invocation-1",
    )
    execution_info = ExecutionInfo(
        checkpoint_id="checkpoint-1",
        checkpoint_ns="",
        task_id="task-1",
        thread_id="thread-1",
        run_id="official-run-1",
        node_attempt=2,
        node_first_attempt_time=123.5,
    )

    result = asyncio.run(
        run_command(
            _command("runtime-context-command"),
            state=wrap_workflow_state_update(
                {"runtime_target_node_id": "continue"}
            ),
            runtime=Runtime(context=context, execution_info=execution_info),
            target_map={"continue": "continue"},
        )
    )

    assert result.goto == "continue"
    projection = result.update[WORKFLOW_STATE_CHANNEL]["command_runtime"]
    assert projection["context"] == {
        "request_id": "request-1",
        "lifecycle_id": "lifecycle-1",
        "caller_run_id": "caller-run-1",
        "operation_id": "operation-1",
        "run_id": "shell-run-1",
        "workflow_id": "workflow-1",
        "workflow_node_id": "inspect-runtime",
        "node_invocation_id": "invocation-1",
    }
    assert projection["execution_info"] == {
        "checkpoint_id": "checkpoint-1",
        "checkpoint_ns": "",
        "task_id": "task-1",
        "thread_id": "thread-1",
        "run_id": "official-run-1",
        "node_attempt": 2,
        "node_first_attempt_time": 123.5,
    }


class _AgentRuns:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def start(self, *args, **kwargs):
        self.calls.append(("start", args, kwargs))
        return AgentRunHandle(
            operation_id=kwargs["operation_id"],
            main_agent_id=args[0],
            assistant_id="assistant-1",
            thread_id=kwargs["thread_id"] or "thread-new",
            run_id="run-start",
            status="pending",
        )

    async def check(self, *args, **kwargs):
        return await self._snapshot("check", *args, **kwargs)

    async def get(self, *args, **kwargs):
        return await self._snapshot("get", *args, **kwargs)

    async def join(self, *args, **kwargs):
        return await self._snapshot("join", *args, **kwargs)

    async def cancel(self, *args, **kwargs):
        return await self._snapshot("cancel", *args, **kwargs)

    async def _snapshot(self, action, *args, **kwargs):
        self.calls.append((action, args, kwargs))
        return AgentRunSnapshot(
            operation_id="agent-operation",
            caller_run_id="caller-run",
            main_agent_id="agent-1",
            main_agent_name="Reviewer",
            assistant_id="assistant-1",
            thread_id=args[0],
            run_id=args[1],
            status={
                "check": "running",
                "get": "running",
                "join": "success",
                "cancel": "interrupted",
            }[action],
            output={"messages": [{"type": "ai", "content": action}]},
        )


@pytest.mark.parametrize("action", ["start", "check", "get", "join", "cancel"])
def test_agent_run_example_has_a_successful_action(action: str) -> None:
    facade = _AgentRuns()
    request = {
        "action": action,
        "target_node_id": "after-agent",
        "main_agent_id": "agent-1",
        "operation_id": "agent-operation",
        "input": [{"role": "user", "content": "Review the artifact."}],
        "thread_id": "thread-1",
        "run_id": "run-1",
    }

    result = asyncio.run(
        run_command(
            _command("agent-run-command"),
            state=wrap_workflow_state_update({"agent_run": request}),
            runtime=Runtime(context=SimpleNamespace(agent_runs=facade)),
            target_map={"after-agent": "after-agent"},
        )
    )

    assert result.goto == "after-agent"
    assert facade.calls[0][0] == action
    if action == "start":
        assert facade.calls[0][1] == (
            "agent-1",
            [{"role": "user", "content": "Review the artifact."}],
        )
        assert facade.calls[0][2] == {
            "operation_id": "agent-operation",
            "thread_id": "thread-1",
        }
    else:
        assert facade.calls[0][1] == ("thread-1", "run-1")
        assert facade.calls[0][2] == {}
    projected = result.update[WORKFLOW_STATE_CHANNEL]["agent_run_result"]
    assert projected["action"] == action
    assert projected["run"]["run_id"] == (
        "run-start" if action == "start" else "run-1"
    )
    if action != "start":
        assert projected["run"]["main_agent_name"] == "Reviewer"
        assert projected["run"]["output"] == {
            "messages": [{"type": "ai", "content": action}]
        }


class _WorkflowRuns:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def start_workflow(self, *args, **kwargs):
        self.calls.append(("start", args, kwargs))
        return WorkflowRunHandle(
            operation_id=kwargs["operation_id"],
            workflow_id=args[0],
            assistant_id="assistant-workflow",
            thread_id="thread-workflow",
            run_id="run-start",
            status="pending",
        )

    async def check(self, *args, **kwargs):
        return await self._snapshots("check", *args, **kwargs)

    async def list(self, *args, **kwargs):
        return await self._snapshots("list", *args, **kwargs)

    async def join(self, *args, **kwargs):
        return await self._snapshots("join", *args, **kwargs)

    async def cancel(self, *args, **kwargs):
        return await self._snapshots("cancel", *args, **kwargs)

    async def _snapshots(self, action, *args, **kwargs):
        self.calls.append((action, args, kwargs))
        return [
            WorkflowRunSnapshot(
                operation_id="workflow-operation",
                caller_run_id="caller-run",
                workflow_id="workflow-1",
                workflow_name="Research workflow",
                assistant_id="assistant-workflow",
                thread_id="thread-workflow",
                run_id="run-1",
                status={
                    "check": "running",
                    "list": "running",
                    "join": "success",
                    "cancel": "interrupted",
                }[action],
                output={WORKFLOW_STATE_CHANNEL: {"action": action}},
            )
        ]


@pytest.mark.parametrize("action", ["start", "check", "list", "join", "cancel"])
def test_workflow_run_example_has_a_successful_action(action: str) -> None:
    facade = _WorkflowRuns()
    request = {
        "action": action,
        "target_node_id": "after-workflow",
        "workflow_id": "workflow-1",
        "operation_id": "workflow-operation",
        "input_state": {"topic": "weather"},
        "run_ids": ["run-1"],
        "statuses": ["pending", "running"],
    }

    result = asyncio.run(
        run_command(
            _command("workflow-run-command"),
            state=wrap_workflow_state_update({"workflow_run": request}),
            runtime=Runtime(context=SimpleNamespace(workflow_runs=facade)),
            target_map={"after-workflow": "after-workflow"},
        )
    )

    assert result.goto == "after-workflow"
    assert facade.calls[0][0] == action
    if action == "start":
        assert facade.calls[0][1] == ("workflow-1",)
        assert facade.calls[0][2] == {
            "operation_id": "workflow-operation",
            "initial_state": {"topic": "weather"},
        }
    elif action == "list":
        assert facade.calls[0][1] == ()
        assert facade.calls[0][2] == {
            "statuses": frozenset({"pending", "running"})
        }
    else:
        assert facade.calls[0][1] == (["run-1"],)
        assert facade.calls[0][2] == {}
    projected = result.update[WORKFLOW_STATE_CHANNEL]["workflow_run_result"]
    assert projected["action"] == action
    assert projected["runs"][0]["run_id"] == (
        "run-start" if action == "start" else "run-1"
    )
    if action != "start":
        assert projected["runs"][0]["workflow_name"] == "Research workflow"
        assert projected["runs"][0]["output"] == {
            WORKFLOW_STATE_CHANNEL: {"action": action}
        }
