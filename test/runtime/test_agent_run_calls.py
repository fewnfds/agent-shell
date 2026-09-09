from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.request_snapshot import LifecycleRunCoordinator
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_RECORD_KEY,
    LIFECYCLE_START_ERROR_KEY,
    lifecycle_input_namespace,
    lifecycle_record_namespace,
)
from agent_shell.runtime.run_calls import RunCaller


class _Store:
    def __init__(self) -> None:
        self.items: dict[tuple[str, ...], dict[str, dict]] = {}
        self.events: list[str] = []

    async def put_item(self, namespace, key, value, *, index=False):
        del index
        self.events.append(f"store:{tuple(namespace)[-1]}:{key}")
        self.items.setdefault(tuple(namespace), {})[key] = deepcopy(value)

    async def get_item(self, namespace, key):
        value = self.items.get(tuple(namespace), {}).get(key)
        return None if value is None else {"key": key, "value": deepcopy(value)}

    async def search_items(self, namespace, *, limit: int, offset: int):
        values = [
            {"key": key, "value": deepcopy(value)}
            for key, value in self.items.get(tuple(namespace), {}).items()
        ]
        return {"items": values[offset : offset + limit]}


class _StreamRun:
    def __init__(self, client: "_Client", thread_id: str, assistant_id: str) -> None:
        self._client = client
        self._thread_id = thread_id
        self._assistant_id = assistant_id

    async def start(self, **kwargs):
        return await self._client.runs.start(
            self._thread_id,
            self._assistant_id,
            **kwargs,
        )


class _Stream:
    def __init__(
        self,
        client: "_Client" | None = None,
        thread_id: str = "",
        assistant_id: str = "",
    ) -> None:
        self.closed = False
        self.events = self._events()
        self.run = (
            _StreamRun(client, thread_id, assistant_id)
            if client is not None
            else None
        )

    async def _events(self):
        if False:
            yield None

    async def __aenter__(self):
        return self

    async def close(self) -> None:
        self.closed = True


class _Threads:
    def __init__(self, client: "_Client") -> None:
        self._client = client
        self.values: dict[str, dict] = {}
        self.states: dict[str, dict] = {}
        self.deleted: list[str] = []
        self._next = 0

    async def create(self, *, metadata):
        self._next += 1
        thread_id = f"thread-{self._next}"
        value = {"thread_id": thread_id, "metadata": deepcopy(metadata)}
        self.values[thread_id] = value
        self.states[thread_id] = {"values": {"messages": []}}
        return deepcopy(value)

    async def get(self, thread_id: str):
        return deepcopy(self.values[thread_id])

    async def update(self, thread_id: str, *, metadata):
        self.values[thread_id]["metadata"] = deepcopy(metadata)
        return deepcopy(self.values[thread_id])

    def stream(self, thread_id: str, *, assistant_id: str):
        return _Stream(self._client, thread_id, assistant_id)

    async def get_state(self, thread_id: str):
        return deepcopy(self.states[thread_id])

    async def delete(self, thread_id: str) -> None:
        self.deleted.append(thread_id)
        self.values.pop(thread_id, None)
        self.states.pop(thread_id, None)


class _Execution:
    def __init__(self, coordinator, binding) -> None:
        self._coordinator = coordinator
        self._binding = binding

    async def execute(self) -> None:
        assert self._binding.run_id_ready is not None
        await self._binding.run_id_ready
        await asyncio.sleep(0)
        await self._coordinator.close_official_session(self._binding.thread_id)


class _Runs:
    def __init__(self, client: "_Client", coordinator: LifecycleRunCoordinator) -> None:
        self._client = client
        self._coordinator = coordinator
        self.values: dict[tuple[str, str], dict] = {}
        self.created: list[dict] = []
        self.cancelled: list[tuple[str, str]] = []
        self.failure: Exception | None = None
        self._next = 0

    async def start(self, thread_id, assistant_id, **kwargs):
        if self.failure is not None:
            raise self.failure
        self._next += 1
        run_id = f"run-{self._next}"
        value = {
            "thread_id": thread_id,
            "run_id": run_id,
            "assistant_id": assistant_id,
            "status": "running",
            "metadata": deepcopy(kwargs["metadata"]),
        }
        self.values[(thread_id, run_id)] = value
        self.created.append(
            {"thread_id": thread_id, "run_id": run_id, **deepcopy(kwargs)}
        )
        key = next(
            key
            for key, binding in self._coordinator._agent_bindings.items()
            if binding.operation_id == kwargs["metadata"]["operation_id"]
            and not binding.run_id
        )
        binding = self._coordinator._agent_bindings[key]
        assert binding.execution_ready is not None
        binding.execution_ready.set_result(_Execution(self._coordinator, binding))
        return deepcopy(value)

    async def get(self, thread_id: str, run_id: str):
        return deepcopy(self.values[(thread_id, run_id)])

    async def join(self, thread_id: str, run_id: str):
        value = self.values[(thread_id, run_id)]
        value["status"] = "success"
        output = {"messages": [{"type": "ai", "content": run_id}]}
        self._client.threads.states[thread_id] = {"values": deepcopy(output)}
        return output

    async def cancel(self, thread_id: str, run_id: str, *, wait=False):
        del wait
        self.cancelled.append((thread_id, run_id))
        self.values[(thread_id, run_id)]["status"] = "interrupted"


class _Assistants:
    def __init__(self, store: _Store) -> None:
        self._store = store

    async def create(self, _graph_id, *, assistant_id, **_kwargs):
        self._store.events.append("assistant")
        return {"assistant_id": assistant_id, "name": _kwargs["name"]}

    async def update(self, *_args, **_kwargs):
        raise AssertionError("matching Assistant names must not be updated")


class _Client:
    def __init__(self) -> None:
        self.store = _Store()
        self.threads = _Threads(self)
        self.runs = None
        self.assistants = _Assistants(self.store)

    async def aclose(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None


class _Detached:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def create(self, coroutine, *, name: str):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task


class _Diagnostics:
    def __init__(self) -> None:
        self.runtime_errors: list[tuple[BaseException, dict]] = []
        self.observation_errors: list[tuple[BaseException, dict]] = []
        self.failure: Exception | None = None

    async def aruntime_error(self, exc, **kwargs) -> None:
        self.runtime_errors.append((exc, kwargs))
        if self.failure is not None:
            raise self.failure

    async def aobservation_error(self, exc, **kwargs) -> None:
        self.observation_errors.append((exc, kwargs))


def _coordinator(profile: dict) -> tuple[LifecycleRunCoordinator, _Client, _Detached]:
    client = _Client()
    detached = _Detached()
    diagnostics = _Diagnostics()
    async def register_run_relation(_coordinator, _relation) -> None:
        return None

    owner = SimpleNamespace(
        new_agent_server_client=lambda: client,
        run_config=lambda: {"recursion_limit": 100},
        register_active_lifecycle=lambda _coordinator: None,
        release_active_lifecycle=lambda _coordinator: None,
        register_run_relation=register_run_relation,
        runtime_diagnostics=diagnostics,
    )
    coordinator = LifecycleRunCoordinator(
        _owner=owner,
        _snapshot=SimpleNamespace(
            main_agent_by_id=lambda _agent_id: profile,
            response_stream_policy=lambda: ResponseStreamPolicy(),
            run_config=lambda: {"recursion_limit": 100},
            lifecycle_configuration=lambda **_kwargs: SimpleNamespace(
                as_store_value=lambda: {"schema_version": 1}
            ),
        ),
        _detached_tasks=detached,
    )
    coordinator._lifecycle_id = "lifecycle-1"
    client.runs = _Runs(client, coordinator)
    return coordinator, client, detached


def test_request_entry_run_start_failure_is_recorded_and_terminal() -> None:
    async def scenario():
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Researcher",
        }
        coordinator, client, _detached = _coordinator(profile)
        coordinator._lifecycle_id = ""
        client.runs.failure = RuntimeError("run creation exploded")

        try:
            await coordinator.start_agent(
                profile,
                [{"role": "user", "content": "hello"}],
                request_id="request-1",
            )
        except RuntimeError as exc:
            assert str(exc) == "run creation exploded"
        else:
            raise AssertionError("run start failure was not raised")

        record = client.store.items[
            lifecycle_record_namespace(coordinator.lifecycle_id)
        ][LIFECYCLE_RECORD_KEY]
        marker = client.store.items[
            lifecycle_input_namespace(coordinator.lifecycle_id)
        ][LIFECYCLE_START_ERROR_KEY]
        diagnostics = coordinator._owner.runtime_diagnostics
        return record, marker, diagnostics, client.store.events

    record, marker, diagnostics, events = asyncio.run(scenario())
    assert record["lifecycle_id"]
    assert record["request_id"] == "request-1"
    assert record["created_at"].endswith("+00:00")
    assert record["entry_subject"] == {
        "graph_kind": "agent",
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Researcher",
    }
    assert marker["status"] == "error"
    assert marker["code"] == "run_start_failed"
    assert marker["message"] == "RuntimeError: run creation exploded"
    assert marker["request_id"] == "request-1"
    assert marker["graph_kind"] == "agent"
    assert marker["subject_name"] == "Researcher"
    assert len(diagnostics.runtime_errors) == 1
    diagnostic, kwargs = diagnostics.runtime_errors[0]
    assert diagnostic.message == "RuntimeError: run creation exploded"
    assert kwargs["detail_exception"].args == ("run creation exploded",)
    assert kwargs["context"].lifecycle_id
    assert diagnostics.observation_errors == []
    assert events[:3] == [
        "store:metadata:lifecycle",
        "store:configuration:snapshot",
        "assistant",
    ]


def test_start_error_marker_survives_diagnostic_write_failure() -> None:
    async def scenario():
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Researcher",
        }
        coordinator, client, _detached = _coordinator(profile)
        coordinator._lifecycle_id = ""
        coordinator._owner.runtime_diagnostics.failure = RuntimeError(
            "diagnostic write exploded"
        )
        client.runs.failure = RuntimeError("run creation exploded")

        try:
            await coordinator.start_agent(
                profile,
                [{"role": "user", "content": "hello"}],
                request_id="request-1",
            )
        except RuntimeError as exc:
            assert str(exc) == "run creation exploded"
        else:
            raise AssertionError("run start failure was not raised")

        return client.store.items[
            lifecycle_input_namespace(coordinator.lifecycle_id)
        ][LIFECYCLE_START_ERROR_KEY]

    marker = asyncio.run(scenario())
    assert marker["status"] == "error"
    assert marker["message"] == "RuntimeError: run creation exploded"


def test_agent_run_facade_is_idempotent_and_can_continue_a_thread() -> None:
    async def scenario() -> None:
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Researcher",
        }
        coordinator, client, detached = _coordinator(profile)
        caller = RunCaller("request-1", "lifecycle-1", "caller-run")

        first = await coordinator.start_agent_run(
            profile["id"],
            [{"role": "user", "content": "first"}],
            operation_id="research",
            caller=caller,
        )
        duplicate = await coordinator.start_agent_run(
            profile["id"],
            [{"role": "user", "content": "ignored retry input"}],
            operation_id="research",
            caller=caller,
        )
        assert duplicate == first
        assert len(client.runs.created) == 1

        joined = await coordinator.join_agent_run(
            first.thread_id,
            first.run_id,
            caller=caller,
        )
        assert joined.status == "success"
        assert joined.output == {
            "messages": [{"type": "ai", "content": first.run_id}]
        }
        await asyncio.gather(*detached.tasks)

        second = await coordinator.start_agent_run(
            profile["id"],
            [{"role": "user", "content": "second"}],
            operation_id="follow-up",
            caller=caller,
            thread_id=first.thread_id,
        )
        assert second.thread_id == first.thread_id
        assert second.run_id != first.run_id
        checked = await coordinator.check_agent_run(
            second.thread_id,
            second.run_id,
            caller=caller,
        )
        assert checked.status == "running"
        cancelled = await coordinator.cancel_agent_run(
            second.thread_id,
            second.run_id,
            caller=caller,
        )
        assert cancelled.status == "interrupted"
        assert client.runs.cancelled == [(second.thread_id, second.run_id)]
        await asyncio.gather(*detached.tasks)

    asyncio.run(scenario())


def test_new_agent_thread_remains_after_its_event_session_closes() -> None:
    async def scenario() -> None:
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Persistent worker",
        }
        coordinator, client, detached = _coordinator(profile)
        caller = RunCaller("request-1", "lifecycle-1", "caller-run")
        caller_stream = _Stream()
        coordinator._sessions["caller-thread"] = SimpleNamespace(
            client=client,
            stream=caller_stream,
        )

        handle = await coordinator.start_agent_run(
            profile["id"],
            [{"role": "user", "content": "persist this"}],
            operation_id="persistent-run",
            caller=caller,
        )
        await asyncio.gather(*detached.tasks)
        assert handle.thread_id in client.threads.values

        joined = await coordinator.join_agent_run(
            handle.thread_id,
            handle.run_id,
            caller=caller,
        )
        assert joined.status == "success"
        await coordinator.close_official_session("caller-thread")
        assert handle.thread_id in client.threads.values
        assert handle.thread_id not in client.threads.deleted

    asyncio.run(scenario())
