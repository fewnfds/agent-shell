from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from agent_shell.runtime.request_snapshot import LifecycleRunCoordinator
from agent_shell.runtime.run_calls import RunCaller


class _Store:
    def __init__(self) -> None:
        self.items: dict[tuple[str, ...], dict[str, dict]] = {}

    async def put_item(self, namespace, key, value, *, index=False):
        del index
        self.items.setdefault(tuple(namespace), {})[key] = deepcopy(value)

    async def search_items(self, namespace, *, limit: int, offset: int):
        values = [
            {"key": key, "value": deepcopy(value)}
            for key, value in self.items.get(tuple(namespace), {}).items()
        ]
        return {"items": values[offset : offset + limit]}


class _Stream:
    def __init__(self) -> None:
        self.closed = False
        self.events = self._events()

    async def _events(self):
        if False:
            yield None

    async def __aenter__(self):
        return self

    async def close(self) -> None:
        self.closed = True


class _Threads:
    def __init__(self) -> None:
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
        del thread_id, assistant_id
        return _Stream()

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
        self._next = 0

    async def create(self, thread_id, assistant_id, **kwargs):
        self._next += 1
        if thread_id is None:
            created = await self._client.threads.create(metadata={})
            thread_id = created["thread_id"]
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
    async def create(self, _graph_id, *, assistant_id, **_kwargs):
        return {"assistant_id": assistant_id}


class _Client:
    def __init__(self) -> None:
        self.store = _Store()
        self.threads = _Threads()
        self.runs = None
        self.assistants = _Assistants()

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


def _coordinator(profile: dict) -> tuple[LifecycleRunCoordinator, _Client, _Detached]:
    client = _Client()
    detached = _Detached()
    owner = SimpleNamespace(
        new_agent_server_client=lambda: client,
        run_config=lambda: {"recursion_limit": 100},
        release_active_lifecycle=lambda _coordinator: None,
    )
    coordinator = LifecycleRunCoordinator(
        _owner=owner,
        _snapshot=SimpleNamespace(main_agent_by_id=lambda _agent_id: profile),
        _detached_tasks=detached,
    )
    coordinator._lifecycle_id = "lifecycle-1"
    client.runs = _Runs(client, coordinator)
    return coordinator, client, detached


def test_agent_run_facade_is_idempotent_and_can_continue_a_thread() -> None:
    async def scenario() -> None:
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Researcher",
            "checkpoint_mode": "enabled",
            "durability": "async",
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


def test_stateless_agent_result_lives_until_the_caller_lifecycle_finishes() -> None:
    async def scenario() -> None:
        profile = {
            "id": "11111111-1111-4111-8111-111111111111",
            "name": "Stateless worker",
            "checkpoint_mode": "disabled",
            "durability": "exit",
        }
        coordinator, client, detached = _coordinator(profile)
        caller = RunCaller("request-1", "lifecycle-1", "caller-run")
        caller_stream = _Stream()
        coordinator._sessions["caller-thread"] = SimpleNamespace(
            client=client,
            stream=caller_stream,
            delete_thread_on_close=False,
            delete_thread_with_lifecycle=False,
        )

        handle = await coordinator.start_agent_run(
            profile["id"],
            [{"role": "user", "content": "one shot"}],
            operation_id="one-shot",
            caller=caller,
        )
        assert handle.checkpoint_mode == "disabled"
        assert client.runs.created[0]["on_completion"] == "keep"
        await asyncio.gather(*detached.tasks)
        assert handle.thread_id in client.threads.values

        joined = await coordinator.join_agent_run(
            handle.thread_id,
            handle.run_id,
            caller=caller,
        )
        assert joined.status == "success"
        await coordinator.close_official_session("caller-thread")
        assert handle.thread_id in client.threads.deleted

    asyncio.run(scenario())
