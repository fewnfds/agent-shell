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

    async def get(self, thread_id: str):
        return deepcopy(self._owner.thread_values[thread_id])

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
            {"key": key, "value": deepcopy(value)}
            for key, value in self._owner.store_items.get(tuple(namespace), {}).items()
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
                        "graph_kind": "workflow",
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
                        "graph_kind": "agent",
                        "main_agent_id": "agent-peer",
                        "main_agent_name": "Peer Agent",
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
            ("workflow-lifecycle", "lifecycle-1", "runs"): {
                "run-entry": {
                    "lifecycle_id": "lifecycle-1",
                    "graph_kind": "workflow",
                    "operation_id": "entry",
                    "caller_run_id": "",
                    "resource_id": "workflow-entry",
                    "resource_name": "Entry Workflow",
                    "on_disconnect": "continue",
                    "assistant_id": "assistant-entry",
                    "thread_id": "thread-entry",
                    "run_id": "run-entry",
                },
                "run-peer": {
                    "lifecycle_id": "lifecycle-1",
                    "graph_kind": "workflow",
                    "operation_id": "peer",
                    "caller_run_id": "run-entry",
                    "resource_id": "workflow-peer",
                    "resource_name": "Peer Workflow",
                    "on_disconnect": "cancel",
                    "assistant_id": "assistant-peer",
                    "thread_id": "thread-peer",
                    "run_id": "run-peer",
                },
            },
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
        client.run_values["thread-peer"].append(
            {
                "run_id": "run-peer-again",
                "assistant_id": "assistant-peer",
                "status": "success",
                "updated_at": "2026-09-05T02:00:00Z",
                "metadata": {
                    "graph_kind": "agent",
                    "main_agent_id": "agent-peer",
                    "main_agent_name": "Peer Agent Renamed",
                },
            }
        )
        filtered = await service.list_page(
            page=1, page_size=10, query="Peer Agent Renamed"
        )
        with pytest.raises(LangGraphRunNotFound):
            await service.state("lifecycle-1", "missing")
        return page, snapshot, graph, state, history, filtered

    page, snapshot, graph, state, history, filtered = asyncio.run(scenario())
    assert page["total"] == 1
    assert page["items"][0]["status"] == "running"
    assert page["items"][0]["run_count"] == 2
    assert page["items"][0]["subjects"] == [
        {"graph_kind": "agent", "id": "agent-peer", "name": "Peer Agent"},
        {
            "graph_kind": "workflow",
            "id": "workflow-entry",
            "name": "Entry Workflow",
        },
    ]
    assert {run["run_id"] for run in snapshot["runs"]} == {
        "run-entry",
        "run-peer",
    }
    assert graph["assistant_id"] == "assistant-peer"
    assert state["state"]["values"]["shared_vars"] == {"answer": 42}
    assert history["history"] == [{"checkpoint_id": "checkpoint-peer"}]
    assert filtered["total"] == 1
    agent_subjects = [
        subject
        for subject in filtered["items"][0]["subjects"]
        if subject["graph_kind"] == "agent"
    ]
    assert agent_subjects == [
        {
            "graph_kind": "agent",
            "id": "agent-peer",
            "name": "Peer Agent Renamed",
        }
    ]


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
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")] == {}


def test_relation_only_thread_joins_monitoring_and_lifecycle_deletion() -> None:
    async def scenario():
        client = _Client()
        client.thread_values["thread-async"] = {
            "thread_id": "thread-async",
            "created_at": "2026-09-05T01:04:00Z",
            "updated_at": "2026-09-05T01:05:00Z",
            "metadata": {},
        }
        client.run_values["thread-async"] = [
            {
                "run_id": "run-async",
                "assistant_id": "assistant-async",
                "status": "running",
                "metadata": {},
            }
        ]
        client.states["thread-async"] = {"values": {"messages": []}}
        client.histories["thread-async"] = [{"checkpoint_id": "checkpoint-async"}]
        client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")][
            "run-async"
        ] = {
            "lifecycle_id": "lifecycle-1",
            "graph_kind": "agent",
            "operation_id": "async:profile-1:run-async",
            "caller_run_id": "run-entry",
            "resource_id": "agent-async",
            "resource_name": "Async Child",
            "on_disconnect": "continue",
            "checkpoint_mode": "enabled",
            "assistant_id": "assistant-async",
            "thread_id": "thread-async",
            "run_id": "run-async",
        }
        service = LangGraphLifecycleService(lambda: client)

        page = await service.list_page(page=1, page_size=10)
        snapshot = await service.snapshot("lifecycle-1")
        cancelled = await service.cancel_active("lifecycle-1")
        deleted = await service.delete("lifecycle-1")
        return client, page, snapshot, cancelled, deleted

    client, page, snapshot, cancelled, deleted = asyncio.run(scenario())
    assert page["items"][0]["run_count"] == 3
    assert {
        (subject["graph_kind"], subject["id"], subject["name"])
        for subject in page["items"][0]["subjects"]
    } >= {("agent", "agent-async", "Async Child")}
    async_run = next(run for run in snapshot["runs"] if run["run_id"] == "run-async")
    assert async_run["metadata"]["main_agent_name"] == "Async Child"
    assert cancelled == 2
    assert deleted == 3
    assert "thread-async" in client.deleted_threads
