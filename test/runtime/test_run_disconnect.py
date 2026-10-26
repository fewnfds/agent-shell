from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    _AgentRunBinding,
    _RunBinding,
)
from agent_shell.runtime.run_calls import GraphRunCallRelation


class _Store:
    def __init__(self) -> None:
        self.items: dict[tuple[str, ...], dict[str, dict]] = {}

    async def put_item(self, namespace, key, value, *, index=False):
        del index
        self.items.setdefault(tuple(namespace), {})[key] = deepcopy(value)


class _Runs:
    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}
        self.cancelled: list[str] = []
        self.releases: dict[str, asyncio.Event] = {}
        self.get_failures: set[str] = set()

    async def get(self, _thread_id: str, run_id: str):
        if run_id in self.get_failures:
            raise RuntimeError(f"cannot inspect {run_id}")
        return {"run_id": run_id, "status": self.statuses[run_id]}

    async def cancel(self, _thread_id: str, run_id: str, *, wait=False):
        del wait
        self.cancelled.append(run_id)
        self.statuses[run_id] = "interrupted"
        self.releases.setdefault(run_id, asyncio.Event()).set()

    async def join(self, _thread_id: str, run_id: str):
        await self.releases.setdefault(run_id, asyncio.Event()).wait()
        return {}


class _Client:
    def __init__(self) -> None:
        self.store = _Store()
        self.runs = _Runs()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


class _Detached:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def create(self, coroutine, *, name: str):
        task = asyncio.create_task(coroutine, name=name)
        self.tasks.append(task)
        return task


def _relation(run_id: str, policy: str, *, caller_run_id: str = ""):
    return GraphRunCallRelation(
        lifecycle_id="lifecycle-1",
        graph_kind="agent",
        operation_id=run_id,
        caller_run_id=caller_run_id,
        resource_id=f"agent-{run_id}",
        resource_name=f"Agent {run_id}",
        on_disconnect=policy,
        assistant_id=f"assistant-{run_id}",
        thread_id=f"thread-{run_id}",
        run_id=run_id,
    )


def test_disconnect_applies_each_run_policy_and_late_registration() -> None:
    async def scenario() -> None:
        client = _Client()
        detached = _Detached()
        registered: dict[str, LifecycleRunCoordinator] = {}
        released: list[LifecycleRunCoordinator] = []

        async def register(coordinator, relation) -> None:
            registered[relation.run_id] = coordinator

        owner = SimpleNamespace(
            new_agent_server_client=lambda: client,
            register_run_relation=register,
            release_active_lifecycle=released.append,
        )
        coordinator = LifecycleRunCoordinator(
            _owner=owner,
            _snapshot=SimpleNamespace(),
            _detached_tasks=detached,
        )
        coordinator._lifecycle_id = "lifecycle-1"
        coordinator._sessions["root"] = object()

        cancel = _relation("run-cancel", "cancel")
        keep = _relation("run-continue", "continue")
        late_cancel = _relation("run-late", "cancel")
        client.runs.statuses = {
            cancel.run_id: "running",
            keep.run_id: "running",
            late_cancel.run_id: "running",
        }
        await coordinator._record_relation(client, cancel)
        await coordinator._record_relation(client, keep)

        await coordinator.disconnect()
        await coordinator._record_relation(client, late_cancel)

        assert client.runs.cancelled == ["run-cancel", "run-late"]
        assert client.runs.statuses["run-continue"] == "running"
        assert set(registered) == {"run-cancel", "run-continue", "run-late"}
        assert released == []

    asyncio.run(scenario())


def test_disconnect_continues_after_one_run_cannot_be_inspected() -> None:
    async def scenario() -> None:
        client = _Client()
        errors: list[dict] = []

        async def record_error(_exc, **kwargs):
            errors.append(kwargs)

        coordinator = LifecycleRunCoordinator(
            _owner=SimpleNamespace(
                new_agent_server_client=lambda: client,
                runtime_diagnostics=SimpleNamespace(aobservation_error=record_error),
            ),
            _snapshot=SimpleNamespace(),
            _detached_tasks=_Detached(),
        )
        coordinator._lifecycle_id = "lifecycle-1"
        failed = _relation("run-failed", "cancel")
        healthy = _relation("run-healthy", "cancel")
        coordinator._relations = {
            failed.run_id: failed,
            healthy.run_id: healthy,
        }
        client.runs.statuses[healthy.run_id] = "running"
        client.runs.get_failures.add(failed.run_id)

        await coordinator.disconnect()

        assert client.runs.cancelled == [healthy.run_id]
        assert len(errors) == 1
        assert errors[0]["code"] == "run_disconnect_cancel_failed"
        assert errors[0]["context"].run_id == failed.run_id

    asyncio.run(scenario())


@pytest.mark.parametrize("graph_kind", ["agent", "workflow"])
@pytest.mark.parametrize("policy", ["cancel", "continue"])
def test_disconnect_before_lifecycle_creation_applies_late_policy_and_settles_readiness(
    graph_kind: str, policy: str
) -> None:
    async def scenario() -> None:
        client = _Client()

        async def register(_coordinator, _relation):
            return None

        coordinator = LifecycleRunCoordinator(
            _owner=SimpleNamespace(
                new_agent_server_client=lambda: client,
                register_run_relation=register,
            ),
            _snapshot=SimpleNamespace(),
            _detached_tasks=_Detached(),
        )
        await coordinator.disconnect()
        coordinator._lifecycle_id = "lifecycle-1"
        relation = _relation("run-pending", policy).model_copy(
            update={"graph_kind": graph_kind}
        )
        future = asyncio.get_running_loop().create_future()
        fields = dict(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            public_model="entry",
            thread_id=relation.thread_id,
            run_id=relation.run_id,
            execution_ready=future,
        )
        if graph_kind == "agent":
            binding = _AgentRunBinding(main_agent={}, messages=[], **fields)
            coordinator._agent_bindings[binding.key] = binding
        else:
            binding = _RunBinding(workflow={}, document=object(), **fields)
            coordinator._bindings[binding.key] = binding
        client.runs.statuses[relation.run_id] = "pending"
        await coordinator._record_relation(client, relation)
        await coordinator.disconnect()

        if policy == "cancel":
            assert client.runs.cancelled == [relation.run_id]
            with pytest.raises(AgentRuntimeError) as failure:
                await future
            assert failure.value.code == "completion_cancelled"
        else:
            assert client.runs.cancelled == []
            assert not future.done()
            future.set_result("ready")
            assert await future == "ready"

    asyncio.run(scenario())
