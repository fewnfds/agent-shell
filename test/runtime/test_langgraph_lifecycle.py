from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from agent_shell.runtime.langgraph_lifecycle import (
    LangGraphLifecycleActive,
    LangGraphLifecycleService,
    LangGraphRunNotFound,
)


class _Threads:
    def __init__(self, owner: "_Client") -> None:
        self._owner = owner

    async def search(self, *, metadata=None, limit: int, offset: int):
        values = list(self._owner.thread_values.values())
        if metadata:
            values = [
                item
                for item in values
                if all(item.get("metadata", {}).get(key) == value for key, value in metadata.items())
            ]
        return deepcopy(values[offset : offset + limit])

    async def get_state(self, thread_id: str):
        return deepcopy(self._owner.states[thread_id])

    async def get_history(self, thread_id: str, *, limit: int):
        return deepcopy(self._owner.histories[thread_id][:limit])

    async def delete(self, thread_id: str) -> None:
        self._owner.deleted_threads.append(thread_id)
        self._owner.thread_values.pop(thread_id)


class _Runs:
    def __init__(self, owner: "_Client") -> None:
        self._owner = owner

    async def list(self, thread_id: str, *, limit: int, offset: int):
        return deepcopy(self._owner.run_values[thread_id][offset : offset + limit])

    async def get(self, thread_id: str, run_id: str):
        for run in self._owner.run_values[thread_id]:
            if run["run_id"] == run_id:
                return deepcopy(run)
        raise LookupError(run_id)

    async def cancel(self, thread_id: str, run_id: str, *, wait: bool = False):
        self._owner.cancelled_runs.append((thread_id, run_id, wait))
        for run in self._owner.run_values[thread_id]:
            if run["run_id"] == run_id:
                run["status"] = "interrupted"
                return
        raise LookupError(run_id)


class _Assistants:
    async def get_graph(self, assistant_id: str):
        return {"assistant_id": assistant_id, "nodes": ["start", "end"]}


class _Store:
    def __init__(self, owner: "_Client") -> None:
        self._owner = owner

    async def list_namespaces(self, *, prefix, limit: int, offset: int):
        namespaces = [
            namespace
            for namespace in self._owner.store_items
            if list(namespace[: len(prefix)]) == prefix
        ]
        return {"namespaces": [list(item) for item in namespaces[offset : offset + limit]]}

    async def search_items(self, namespace, *, limit: int, offset: int):
        items = [
            {"key": key}
            for key in self._owner.store_items.get(tuple(namespace), {})
        ]
        return {"items": items[offset : offset + limit]}

    async def delete_item(self, namespace, key: str) -> None:
        self._owner.store_items[tuple(namespace)].pop(key)


class _Client:
    def __init__(self) -> None:
        self.thread_values = {
            "thread-entry": {
                "thread_id": "thread-entry",
                "created_at": "2026-09-05T01:00:00Z",
                "updated_at": "2026-09-05T01:01:00Z",
                "metadata": {
                    "lifecycle_id": "lifecycle-1",
                    "request_id": "request-1",
                    "workflow_id": "workflow-entry",
                    "operation_id": "entry",
                },
            },
            "thread-peer": {
                "thread_id": "thread-peer",
                "created_at": "2026-09-05T01:02:00Z",
                "updated_at": "2026-09-05T01:03:00Z",
                "metadata": {
                    "lifecycle_id": "lifecycle-1",
                    "request_id": "request-1",
                    "workflow_id": "workflow-peer",
                    "caller_run_id": "run-entry",
                    "operation_id": "peer",
                },
            },
        }
        self.run_values = {
            "thread-entry": [
                {
                    "run_id": "run-entry",
                    "assistant_id": "assistant-entry",
                    "status": "success",
                    "metadata": {
                        "workflow_id": "workflow-entry",
                        "workflow_name": "Entry Workflow",
                        "operation_id": "entry",
                    },
                }
            ],
            "thread-peer": [
                {
                    "run_id": "run-peer",
                    "assistant_id": "assistant-peer",
                    "status": "running",
                    "metadata": {
                        "workflow_id": "workflow-peer",
                        "workflow_name": "Peer Workflow",
                        "caller_run_id": "run-entry",
                        "operation_id": "peer",
                    },
                }
            ],
        }
        self.states = {
            "thread-entry": {"values": {"shared_vars": {"answer": 42}}},
            "thread-peer": {"values": {"shared_vars": {"peer": True}}},
        }
        self.histories = {
            "thread-entry": [{"checkpoint_id": "checkpoint-entry"}],
            "thread-peer": [{"checkpoint_id": "checkpoint-peer"}],
        }
        self.store_items = {
            ("workflow-lifecycle", "lifecycle-1", "input"): {"request": {}},
        }
        self.cancelled_runs: list[tuple[str, str, bool]] = []
        self.deleted_threads: list[str] = []
        self.threads = _Threads(self)
        self.runs = _Runs(self)
        self.assistants = _Assistants()
        self.store = _Store(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None


def test_lifecycle_aggregates_equal_runs_and_forwards_public_debug_apis() -> None:
    async def scenario():
        client = _Client()
        service = LangGraphLifecycleService(lambda: client)
        page = await service.list_page(page=1, page_size=10)
        snapshot = await service.snapshot("lifecycle-1")
        graph = await service.graph("lifecycle-1", "run-peer")
        state = await service.state("lifecycle-1", "run-entry")
        history = await service.history("lifecycle-1", "run-peer", limit=5)
        with pytest.raises(LangGraphRunNotFound):
            await service.state("lifecycle-1", "missing")
        return page, snapshot, graph, state, history

    page, snapshot, graph, state, history = asyncio.run(scenario())
    assert page["total"] == 1
    assert page["items"][0]["status"] == "running"
    assert page["items"][0]["run_count"] == 2
    assert {run["run_id"] for run in snapshot["runs"]} == {
        "run-entry",
        "run-peer",
    }
    assert graph["assistant_id"] == "assistant-peer"
    assert state["state"]["values"]["shared_vars"] == {"answer": 42}
    assert history["history"] == [{"checkpoint_id": "checkpoint-peer"}]


def test_lifecycle_cancels_every_active_run_and_deletes_only_terminal_data() -> None:
    async def scenario():
        client = _Client()
        service = LangGraphLifecycleService(lambda: client)
        with pytest.raises(LangGraphLifecycleActive):
            await service.delete("lifecycle-1")
        cancelled = await service.cancel_active("lifecycle-1")
        deleted = await service.delete("lifecycle-1")
        return client, cancelled, deleted

    client, cancelled, deleted = asyncio.run(scenario())
    assert cancelled == 1
    assert client.cancelled_runs == [("thread-peer", "run-peer", False)]
    assert deleted == 2
    assert set(client.deleted_threads) == {"thread-entry", "thread-peer"}
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "input")] == {}
