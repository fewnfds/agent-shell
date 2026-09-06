from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent_shell.runtime.errors import AgentRuntimeError, encode_server_run_error
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    _OfficialRunEventStream,
)
from agent_shell.runtime.run_calls import RunCaller, relation_key


def _relation(run_id: str, *, operation_id: str, caller_run_id: str) -> dict[str, object]:
    return {
        "lifecycle_id": "lifecycle-1",
        "operation_id": operation_id,
        "caller_run_id": caller_run_id,
        "workflow_id": f"workflow-{run_id}",
        "workflow_name": f"Workflow {run_id}",
        "assistant_id": f"assistant-{run_id}",
        "thread_id": f"thread-{run_id}",
        "run_id": run_id,
    }


class _Runs:
    def __init__(self, relations: list[dict[str, object]], statuses: dict[str, str]) -> None:
        self._relations = relations
        self.statuses = statuses
        self.cancelled: list[str] = []

    async def list(self, thread_id: str, *, limit: int, offset: int):
        values = [
            {
                "run_id": relation["run_id"],
                "assistant_id": relation["assistant_id"],
                "status": self.statuses[str(relation["run_id"])],
                "metadata": {
                    "operation_id": relation["operation_id"],
                    "caller_run_id": relation["caller_run_id"],
                    "workflow_id": relation["workflow_id"],
                    "workflow_name": relation["workflow_name"],
                },
            }
            for relation in self._relations
            if relation["thread_id"] == thread_id
        ]
        return values[offset : offset + limit]

    async def get(self, thread_id: str, run_id: str):
        return {
            "thread_id": thread_id,
            "run_id": run_id,
            "assistant_id": f"assistant-{run_id}",
            "status": self.statuses[run_id],
        }

    async def join(self, _thread_id: str, run_id: str):
        self.statuses[run_id] = "success"
        return {"shared_vars": {"joined": run_id}}

    async def cancel(self, _thread_id: str, run_id: str, *, wait=False):
        del wait
        self.cancelled.append(run_id)
        self.statuses[run_id] = "interrupted"


class _Threads:
    def __init__(self, relations: list[dict[str, object]]) -> None:
        self._relations = relations

    async def search(self, *, metadata, limit: int, offset: int):
        lifecycle_id = metadata["lifecycle_id"]
        values = [
            {
                "thread_id": relation["thread_id"],
                "metadata": {
                    "lifecycle_id": relation["lifecycle_id"],
                    "operation_id": relation["operation_id"],
                    "caller_run_id": relation["caller_run_id"],
                    "workflow_id": relation["workflow_id"],
                },
            }
            for relation in self._relations
            if relation["lifecycle_id"] == lifecycle_id
        ]
        return values[offset : offset + limit]

    async def get_state(self, thread_id: str):
        return {"values": {"shared_vars": {"thread_id": thread_id}}}


class _Store:
    def __init__(self, relations: list[dict[str, object]]) -> None:
        self._relations = relations

    async def search_items(self, namespace, *, limit: int, offset: int):
        lifecycle_id = namespace[1]
        values = [
            {
                "key": relation["run_id"],
                "value": {
                    "lifecycle_id": relation["lifecycle_id"],
                    "graph_kind": "workflow",
                    "operation_id": relation["operation_id"],
                    "caller_run_id": relation["caller_run_id"],
                    "resource_id": relation["workflow_id"],
                    "resource_name": relation["workflow_name"],
                    "assistant_id": relation["assistant_id"],
                    "thread_id": relation["thread_id"],
                    "run_id": relation["run_id"],
                },
            }
            for relation in self._relations
            if relation["lifecycle_id"] == lifecycle_id
        ]
        return {"items": values[offset : offset + limit]}


class _Client:
    def __init__(self, relations: list[dict[str, object]], statuses: dict[str, str]):
        self.runs = _Runs(relations, statuses)
        self.threads = _Threads(relations)
        self.store = _Store(relations)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


def _coordinator(client: _Client) -> LifecycleRunCoordinator:
    coordinator = LifecycleRunCoordinator(
        _owner=SimpleNamespace(new_agent_server_client=lambda: client),
        _snapshot=SimpleNamespace(),
        _detached_tasks=SimpleNamespace(),
    )
    coordinator._lifecycle_id = "lifecycle-1"
    return coordinator


def test_run_commands_treat_every_lifecycle_run_as_an_equal_target() -> None:
    async def scenario() -> None:
        relations = [
            _relation("run-active", operation_id="active", caller_run_id="run-a"),
            _relation("run-error", operation_id="error", caller_run_id="run-b"),
            _relation("run-join", operation_id="join", caller_run_id="run-c"),
        ]
        client = _Client(
            relations,
            {
                "run-active": "running",
                "run-error": "error",
                "run-join": "running",
            },
        )
        coordinator = _coordinator(client)
        caller = RunCaller("request-1", "lifecycle-1", "unrelated-run")

        checked = await coordinator.check_workflow_runs(
            ["run-active", "run-error", "missing"],
            caller=caller,
        )
        assert [item.status for item in checked] == ["running", "error", "not_found"]
        assert checked[1].output == {
            "shared_vars": {"thread_id": "thread-run-error"}
        }

        joined = await coordinator.join_workflow_runs(["run-join"], caller=caller)
        assert joined[0].status == "success"
        assert joined[0].output == {"shared_vars": {"joined": "run-join"}}

        cancelled = await coordinator.cancel_workflow_runs(
            ["run-active"],
            caller=caller,
        )
        assert cancelled[0].status == "interrupted"
        assert client.runs.cancelled == ["run-active"]

    asyncio.run(scenario())


def test_official_run_cancellation_skips_a_terminal_run() -> None:
    async def scenario() -> None:
        client = _Client([], {"run-finished": "error"})
        coordinator = _coordinator(client)
        await coordinator.cancel_official_run("thread-finished", "run-finished")
        assert client.runs.cancelled == []

    asyncio.run(scenario())


def test_relation_key_preserves_caller_and_operation_boundaries() -> None:
    assert relation_key("a", "b:c") != relation_key("a:b", "c")


def test_official_run_stream_restores_safe_product_error() -> None:
    async def events():
        yield {
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {
                    "event": "failed",
                    "error": encode_server_run_error(
                        AgentRuntimeError(
                            "workflow.command_failed",
                            "The Command Node script failed.",
                            status_code=422,
                        )
                    ),
                },
            },
        }

    async def close_session(_thread_id: str) -> None:
        return None

    async def scenario() -> None:
        stream = _OfficialRunEventStream(
            events(),
            SimpleNamespace(close_official_session=close_session),
            "thread-1",
        )
        with pytest.raises(AgentRuntimeError) as captured:
            async for _event in stream:
                pass
        assert captured.value.code == "workflow.command_failed"
        assert captured.value.safe_message == "The Command Node script failed."
        assert captured.value.status_code == 422

    asyncio.run(scenario())
