from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    _OfficialRunEventGraph,
    _OfficialRunEventStream,
    _RunBinding,
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
        return {"state": {"joined": run_id}}

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
        return {"values": {"state": {"thread_id": thread_id}}}


class _Store:
    def __init__(self, relations: list[dict[str, object]]) -> None:
        self._relations = relations
        self.search_count = 0
        self.search_started: asyncio.Event | None = None
        self.release_search: asyncio.Event | None = None

    async def search_items(self, namespace, *, limit: int, offset: int):
        self.search_count += 1
        if self.search_started is not None:
            self.search_started.set()
        if self.release_search is not None:
            await self.release_search.wait()
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
                    "on_disconnect": "cancel",
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
        assert checked[1].output == {"thread_id": "thread-run-error"}

        joined = await coordinator.join_workflow_runs(["run-join"], caller=caller)
        assert joined[0].status == "success"
        assert joined[0].output == {"joined": "run-join"}

        cancelled = await coordinator.cancel_workflow_runs(
            ["run-active"],
            caller=caller,
        )
        assert cancelled[0].status == "interrupted"
        assert client.runs.cancelled == ["run-active"]

    asyncio.run(scenario())


def test_concurrent_workflow_start_reuses_the_pending_operation() -> None:
    async def scenario() -> None:
        workflow = {
            "id": "workflow-pending",
            "name": "Pending Workflow",
            "enabled": True,
            "on_disconnect": "cancel",
        }
        client = _Client([], {"run-pending": "running"})
        coordinator = LifecycleRunCoordinator(
            _owner=SimpleNamespace(new_agent_server_client=lambda: client),
            _snapshot=SimpleNamespace(
                workflow_by_id=lambda _workflow_id: workflow,
                workflow_document=lambda _workflow_id: object(),
            ),
            _detached_tasks=SimpleNamespace(),
        )
        coordinator._lifecycle_id = "lifecycle-1"
        caller = RunCaller("request-1", "lifecycle-1", "caller-run")
        loop = asyncio.get_running_loop()
        pending = _RunBinding(
            workflow=workflow,
            document=object(),
            request_id=caller.request_id,
            lifecycle_id=caller.lifecycle_id,
            public_model=workflow["name"],
            caller_run_id=caller.run_id,
            operation_id="same-operation",
            assistant_id="assistant-pending",
            thread_id="thread-pending",
            run_id_ready=loop.create_future(),
            handle_ready=loop.create_future(),
            execution_ready=loop.create_future(),
        )
        coordinator._bindings[pending.key] = pending

        cancelled_duplicate = asyncio.create_task(
            coordinator.start_workflow_run(
                workflow["id"],
                operation_id="same-operation",
                caller=caller,
                initial_state={},
            )
        )
        await asyncio.sleep(0)
        cancelled_duplicate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_duplicate
        assert pending.handle_ready is not None
        assert not pending.handle_ready.cancelled()

        async def finish_first_start() -> None:
            await asyncio.sleep(0)
            pending.run_id = "run-pending"
            assert pending.run_id_ready is not None
            pending.run_id_ready.set_result(pending.run_id)
            await asyncio.sleep(0)
            assert not duplicate_start.done()
            relation = coordinator._workflow_relation(pending)
            assert pending.handle_ready is not None
            pending.handle_ready.set_result(
                coordinator._handle(
                    relation,
                    await client.runs.get(relation.thread_id, relation.run_id),
                )
            )

        first_start = asyncio.create_task(finish_first_start())
        duplicate_start = asyncio.create_task(
            coordinator.start_workflow_run(
                workflow["id"],
                operation_id="same-operation",
                caller=caller,
                initial_state={"ignored": "retry input"},
            )
        )
        duplicate = await duplicate_start
        await first_start

        assert duplicate.thread_id == "thread-pending"
        assert duplicate.run_id == "run-pending"
        assert duplicate.operation_id == "same-operation"

        failed = _RunBinding(
            workflow=workflow,
            document=object(),
            request_id=caller.request_id,
            lifecycle_id=caller.lifecycle_id,
            public_model=workflow["name"],
            caller_run_id=caller.run_id,
            operation_id="failed-operation",
            assistant_id="assistant-failed",
            thread_id="thread-failed",
            run_id="run-failed",
            run_id_ready=loop.create_future(),
            handle_ready=loop.create_future(),
            execution_ready=loop.create_future(),
        )
        coordinator._bindings[failed.key] = failed
        failed_duplicate = asyncio.create_task(
            coordinator.start_workflow_run(
                workflow["id"],
                operation_id="failed-operation",
                caller=caller,
                initial_state={},
            )
        )
        await asyncio.sleep(0)
        coordinator._fail_handle_ready(
            failed,
            OSError("relation store is unavailable"),
        )
        with pytest.raises(OSError, match="relation store is unavailable"):
            await failed_duplicate

    asyncio.run(scenario())


def test_concurrent_workflow_starts_claim_operation_before_relation_lookup() -> None:
    async def scenario() -> None:
        existing = _relation(
            "run-existing",
            operation_id="same-operation",
            caller_run_id="caller-run",
        )
        workflow = {
            "id": existing["workflow_id"],
            "name": existing["workflow_name"],
            "enabled": True,
            "on_disconnect": "cancel",
        }
        client = _Client([existing], {"run-existing": "running"})
        client.store.search_started = asyncio.Event()
        client.store.release_search = asyncio.Event()
        coordinator = LifecycleRunCoordinator(
            _owner=SimpleNamespace(new_agent_server_client=lambda: client),
            _snapshot=SimpleNamespace(
                workflow_by_id=lambda _workflow_id: workflow,
                workflow_document=lambda _workflow_id: object(),
                python_schema_source=lambda _schema_id: None,
            ),
            _detached_tasks=SimpleNamespace(),
        )
        coordinator._lifecycle_id = "lifecycle-1"
        caller = RunCaller("request-1", "lifecycle-1", "caller-run")

        first = asyncio.create_task(
            coordinator.start_workflow_run(
                str(workflow["id"]),
                operation_id="same-operation",
                caller=caller,
                initial_state={},
            )
        )
        await client.store.search_started.wait()
        duplicate = asyncio.create_task(
            coordinator.start_workflow_run(
                str(workflow["id"]),
                operation_id="same-operation",
                caller=caller,
                initial_state={"ignored": "retry input"},
            )
        )
        await asyncio.sleep(0)
        client.store.release_search.set()
        first_handle, duplicate_handle = await asyncio.gather(first, duplicate)

        assert duplicate_handle == first_handle
        assert client.store.search_count == 1

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


def test_official_run_stream_restores_source_error_and_projects_readable_event() -> None:
    class ProviderGatewayError(RuntimeError):
        pass

    try:
        raise ProviderGatewayError("gateway rejected request body")
    except ProviderGatewayError as cause:
        try:
            raise AgentRuntimeError(
                "provider_request_failed",
                "classified provider failure",
                status_code=502,
            ) from cause
        except AgentRuntimeError as source_error:
            transported_error = str(source_error)

    async def events():
        yield {
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {
                    "event": "failed",
                    "error": transported_error,
                },
            },
        }

    async def close_session(_thread_id: str) -> None:
        return None

    async def scenario() -> tuple[AgentRuntimeError, list[Mapping[str, object]]]:
        stream = _OfficialRunEventStream(
            events(),
            SimpleNamespace(close_official_session=close_session),
            "thread-1",
        )
        projected: list[Mapping[str, object]] = []
        with pytest.raises(AgentRuntimeError) as captured:
            async for event in stream:
                projected.append(event)
        return captured.value, projected

    error, projected = asyncio.run(scenario())
    assert error.code == "provider_request_failed"
    assert error.message == "ProviderGatewayError: gateway rejected request body"
    assert error.status_code == 502
    assert error.source_exception_type == "ProviderGatewayError"
    assert error.diagnostic_id == ""
    assert projected[0]["params"]["data"] == {
        "event": "failed",
        "error": "ProviderGatewayError: gateway rejected request body",
        "error_code": "provider_request_failed",
        "exception_type": "ProviderGatewayError",
    }


def test_official_run_stream_preserves_unencoded_failure_text() -> None:
    async def events():
        yield {
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {
                    "event": "failed",
                    "error": "worker exited while opening C:\\runtime\\provider.log",
                },
            },
        }

    async def close_session(_thread_id: str) -> None:
        return None

    async def scenario() -> tuple[AgentRuntimeError, list[Mapping[str, object]]]:
        stream = _OfficialRunEventStream(
            events(),
            SimpleNamespace(close_official_session=close_session),
            "thread-raw",
        )
        projected: list[Mapping[str, object]] = []
        with pytest.raises(AgentRuntimeError) as captured:
            async for event in stream:
                projected.append(event)
        return captured.value, projected

    error, projected = asyncio.run(scenario())
    assert error.code == "official_run_failed"
    assert error.message == "worker exited while opening C:\\runtime\\provider.log"
    assert projected[0]["params"]["data"] == {
        "event": "failed",
        "error": "worker exited while opening C:\\runtime\\provider.log",
        "error_code": "official_run_failed",
    }


def test_official_run_stream_ends_subscription_on_interrupted_root_terminal() -> None:
    async def events():
        yield {
            "method": "lifecycle",
            "params": {"namespace": [], "data": {"event": "interrupted"}},
        }

    async def close_session(_thread_id: str) -> None:
        return None

    async def scenario() -> list[Mapping[str, object]]:
        stream = _OfficialRunEventStream(
            events(),
            SimpleNamespace(close_official_session=close_session),
            "thread-interrupted",
        )
        return [event async for event in stream]

    projected = asyncio.run(scenario())
    assert [
        event["params"]["data"]["event"]  # type: ignore[index]
        for event in projected
    ] == ["interrupted"]


def test_official_run_stream_ignores_nested_lifecycle_terminal() -> None:
    async def events():
        yield {
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "data": {
                    "event": "interrupted",
                    "namespace": ["child:node-invocation-1"],
                    "graph_name": "child",
                },
            },
        }
        yield {
            "method": "lifecycle",
            "params": {"namespace": [], "data": {"event": "completed"}},
        }

    async def close_session(_thread_id: str) -> None:
        return None

    async def scenario() -> list[Mapping[str, object]]:
        stream = _OfficialRunEventStream(
            events(),
            SimpleNamespace(close_official_session=close_session),
            "thread-nested",
        )
        return [event async for event in stream]

    projected = asyncio.run(scenario())
    assert [
        event["params"]["data"]["event"]  # type: ignore[index]
        for event in projected
    ] == ["interrupted", "completed"]


def test_official_event_graph_exposes_the_run_terminal_status() -> None:
    """The production wiring must carry the Run's own end into the projector."""

    async def events(event: str):
        yield {
            "method": "lifecycle",
            "params": {"namespace": [], "data": {"event": event}},
        }

    async def close_session(_thread_id: str) -> None:
        return None

    def terminal_status_for(event: str) -> str:
        stream = _OfficialRunEventStream(
            events(event),
            SimpleNamespace(close_official_session=close_session),
            "thread-status",
        )
        graph = _OfficialRunEventGraph(stream)
        assert graph.terminal_status == ""

        async def drain() -> None:
            try:
                async for _item in await graph.astream_events({}, version="v3"):
                    pass
            except BaseException:
                # `failed`/`error`/`timeout` keep raising so the response layer
                # can classify them; the status must be readable either way.
                pass

        asyncio.run(drain())
        return graph.terminal_status

    # `completed` stays readable; if it were reported as "" the response layer
    # could not tell this apart from a stream that never reached a terminal.
    assert terminal_status_for("completed") == "completed"
    for event in ("failed", "error", "interrupted", "cancelled", "timeout"):
        assert terminal_status_for(event) == event
