from __future__ import annotations

import asyncio
from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from agent_shell.runtime.langgraph_lifecycle import (
    LangGraphLifecycleActive,
    LangGraphLifecycleService,
    LangGraphRunNotFound,
)
from agent_shell.runtime.lifecycle_store import LIFECYCLE_START_ERROR_KEY


class _NotFound(LookupError):
    status_code = 404


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

    async def get_history(self, thread_id: str, *, limit: int, before=None):
        del before
        return deepcopy(self._owner.histories[thread_id][:limit])

    async def get(self, thread_id: str):
        try:
            return deepcopy(self._owner.thread_values[thread_id])
        except KeyError as exc:
            raise _NotFound(thread_id) from exc

    async def delete(self, thread_id: str) -> None:
        self._owner.deleted_threads.append(thread_id)
        self._owner.thread_values.pop(thread_id)


class _Runs:
    def __init__(self, owner: "_Client") -> None:
        self._owner = owner

    async def list(self, thread_id: str, *, limit: int, offset: int):
        if thread_id in self._owner.run_list_errors:
            raise self._owner.run_list_errors[thread_id]
        try:
            values = self._owner.run_values[thread_id]
        except KeyError as exc:
            raise _NotFound(thread_id) from exc
        return deepcopy(values[offset : offset + limit])

    async def get(self, thread_id: str, run_id: str):
        try:
            runs = self._owner.run_values[thread_id]
        except KeyError as exc:
            raise _NotFound(thread_id) from exc
        for run in runs:
            if run["run_id"] == run_id:
                return deepcopy(run)
        raise _NotFound(run_id)

    async def cancel(self, thread_id: str, run_id: str, *, wait: bool = False):
        self._owner.cancelled_runs.append((thread_id, run_id, wait))
        for run in self._owner.run_values[thread_id]:
            if run["run_id"] == run_id:
                run["status"] = "interrupted"
                return
        raise LookupError(run_id)


class _Assistants:
    def __init__(self) -> None:
        self.graph_reads: list[str] = []

    async def get_graph(self, assistant_id: str):
        self.graph_reads.append(assistant_id)
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

    async def get_item(self, namespace, key: str):
        value = self._owner.store_items.get(tuple(namespace), {}).get(key)
        if value is None:
            return None
        return {
            "namespace": list(namespace),
            "key": key,
            "value": deepcopy(value),
            "created_at": "2026-09-05T00:59:00Z",
            "updated_at": "2026-09-05T00:59:00Z",
        }

    async def search_items(self, namespace, *, limit: int, offset: int):
        items = [
            {
                "namespace": list(namespace),
                "key": key,
                "value": deepcopy(value),
                "created_at": "2026-09-05T01:00:00Z",
                "updated_at": "2026-09-05T01:01:00Z",
            }
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
                    "graph_kind": "agent",
                    "operation_id": "peer",
                    "caller_run_id": "run-entry",
                    "resource_id": "agent-peer",
                    "resource_name": "Peer Agent",
                    "on_disconnect": "cancel",
                    "assistant_id": "assistant-peer",
                    "thread_id": "thread-peer",
                    "run_id": "run-peer",
                },
            },
        }
        self.cancelled_runs: list[tuple[str, str, bool]] = []
        self.deleted_threads: list[str] = []
        self.run_list_errors: dict[str, Exception] = {}
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
    assert {thread["thread_id"] for thread in snapshot["threads"]} == {
        "thread-entry",
        "thread-peer",
    }
    peer_thread = next(
        thread for thread in snapshot["threads"]
        if thread["thread_id"] == "thread-peer"
    )
    assert [run["run_id"] for run in peer_thread["runs"]] == ["run-peer"]
    assert peer_thread["runs"][0]["run"]["status"] == "running"
    assert peer_thread["runs"][0]["relation"]["resource_name"] == "Peer Agent"
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


def test_run_start_error_is_a_terminal_lifecycle_without_an_official_run() -> None:
    async def scenario():
        client = _Client()
        client.thread_values.clear()
        client.run_values.clear()
        client.store_items = {
            ("workflow-lifecycle", "lifecycle-start-error", "input"): {
                LIFECYCLE_START_ERROR_KEY: {
                    "status": "error",
                    "code": "run_start_failed",
                    "message": "RuntimeError: run creation exploded",
                    "exception_type": "RuntimeError",
                    "occurred_at": "2026-09-07T15:07:55.700+00:00",
                    "request_id": "request-start-error",
                    "graph_kind": "agent",
                    "subject_id": "agent-one",
                    "subject_name": "Agent One",
                    "thread_id": "thread-empty",
                }
            }
        }
        service = LangGraphLifecycleService(lambda: client)
        page = await service.list_page(page=1, page_size=10)
        return page["items"][0]

    item = asyncio.run(scenario())
    assert item["status"] == "error"
    assert item["request_id"] == "request-start-error"
    assert item["run_count"] == 0
    assert item["active_run_count"] == 0
    assert item["subjects"] == [
        {"graph_kind": "agent", "id": "agent-one", "name": "Agent One"}
    ]
    assert item["start_error"]["message"] == "RuntimeError: run creation exploded"


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
        client.thread_values["thread-detached"] = {
            "thread_id": "thread-detached",
            "created_at": "2026-09-05T01:04:00Z",
            "updated_at": "2026-09-05T01:05:00Z",
            "metadata": {},
        }
        client.run_values["thread-detached"] = [
            {
                "run_id": "run-detached",
                "assistant_id": "assistant-detached",
                "status": "running",
                "metadata": {},
            }
        ]
        client.states["thread-detached"] = {"values": {"messages": []}}
        client.histories["thread-detached"] = [{"checkpoint_id": "checkpoint-detached"}]
        client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")][
            "run-detached"
        ] = {
            "lifecycle_id": "lifecycle-1",
            "graph_kind": "agent",
            "operation_id": "detached-agent",
            "caller_run_id": "run-entry",
            "resource_id": "agent-detached",
            "resource_name": "Detached Agent",
            "on_disconnect": "continue",
            "checkpoint_mode": "enabled",
            "assistant_id": "assistant-detached",
            "thread_id": "thread-detached",
            "run_id": "run-detached",
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
    } >= {("agent", "agent-detached", "Detached Agent")}
    relation_thread = next(
        thread for thread in snapshot["threads"]
        if thread["thread_id"] == "thread-detached"
    )
    relation_run = relation_thread["runs"][0]
    assert relation_run["run"]["metadata"]["main_agent_name"] == "Detached Agent"
    assert cancelled == 2
    assert deleted == 3
    assert "thread-detached" in client.deleted_threads


def test_snapshot_groups_multiple_runs_and_export_uses_public_resources() -> None:
    async def scenario():
        client = _Client()
        client.run_values["thread-peer"].append(
            {
                "run_id": "run-peer-2",
                "thread_id": "thread-peer",
                "assistant_id": "assistant-peer",
                "created_at": "2026-09-05T01:04:00Z",
                "updated_at": "2026-09-05T01:05:00Z",
                "status": "success",
                "metadata": {},
                "multitask_strategy": "enqueue",
            }
        )
        client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")][
            "run-peer-2"
        ] = {
            "lifecycle_id": "lifecycle-1",
            "graph_kind": "agent",
            "operation_id": "peer-2",
            "caller_run_id": "run-peer",
            "resource_id": "agent-peer",
            "resource_name": "Peer Agent",
            "on_disconnect": "continue",
            "checkpoint_mode": "enabled",
            "assistant_id": "assistant-peer",
            "thread_id": "thread-peer",
            "run_id": "run-peer-2",
        }
        service = LangGraphLifecycleService(lambda: client)
        snapshot = await service.snapshot("lifecycle-1")
        store = await service.store("lifecycle-1")
        archive = await service.export("lifecycle-1")
        return client, snapshot, store, archive

    client, snapshot, store, exported = asyncio.run(scenario())
    peer_thread = next(
        thread for thread in snapshot["threads"]
        if thread["thread_id"] == "thread-peer"
    )
    assert [run["run_id"] for run in peer_thread["runs"]] == [
        "run-peer",
        "run-peer-2",
    ]
    assert snapshot["run_count"] == 3
    assert [namespace["namespace"][-1] for namespace in store["namespaces"]] == [
        "input",
        "runs",
    ]
    assert store["namespaces"][0]["items"][0]["created_at"]

    with ZipFile(BytesIO(exported.content)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        archived_snapshot = json.loads(archive.read("snapshot.json"))
        archived_store = json.loads(archive.read("store.json"))
    assert manifest["schema_version"] == 1
    assert manifest["atomic"] is False
    assert all(item["status"] == "available" for item in manifest["files"])
    assert "assistants/assistant-peer/graph.json" in names
    assert "threads/thread-peer/state.json" in names
    assert "threads/thread-peer/history.json" in names
    assert archived_snapshot["run_count"] == 3
    assert len(archived_store["namespaces"]) == 2
    assert client.assistants.graph_reads.count("assistant-peer") == 1


def test_deleted_stateless_thread_remains_explicit_until_lifecycle_retention() -> None:
    async def scenario():
        client = _Client()
        relation = client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")][
            "run-peer"
        ]
        relation["checkpoint_mode"] = "disabled"
        client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")] = {
            "run-peer": relation
        }
        client.thread_values.clear()
        client.run_values.clear()
        service = LangGraphLifecycleService(lambda: client)
        page = await service.list_page(page=1, page_size=10)
        snapshot = await service.snapshot("lifecycle-1")
        archive = await service.export("lifecycle-1")
        deleted = await service.delete("lifecycle-1")
        return client, page, snapshot, archive, deleted

    client, page, snapshot, exported, deleted = asyncio.run(scenario())
    assert page["items"][0]["status"] == "unavailable"
    assert page["items"][0]["run_count"] == 1
    assert snapshot["threads"][0]["thread"] is None
    assert snapshot["threads"][0]["runs"][0]["run"] is None
    assert snapshot["threads"][0]["runs"][0]["error"]["code"] == "run_unavailable"
    with ZipFile(BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert any(item["status"] == "error" for item in manifest["files"])
    assert deleted == 0
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "input")] == {}
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")] == {}


def test_lifecycle_delete_stops_when_official_run_observation_is_uncertain() -> None:
    async def scenario():
        client = _Client()
        for runs in client.run_values.values():
            for run in runs:
                run["status"] = "success"
        client.run_list_errors["thread-peer"] = ConnectionError("Agent Server unavailable")
        service = LangGraphLifecycleService(lambda: client)

        snapshot = await service.snapshot("lifecycle-1")
        with pytest.raises(RuntimeError, match="official Thread/Run status is unavailable"):
            await service.delete("lifecycle-1")
        return client, snapshot

    client, snapshot = asyncio.run(scenario())
    peer = next(
        thread for thread in snapshot["threads"]
        if thread["thread_id"] == "thread-peer"
    )
    assert peer["error"]["code"] == "runs_unavailable"
    assert client.deleted_threads == []
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "input")]
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")]


def test_retention_excludes_active_then_deletes_terminal_lifecycle_data() -> None:
    async def scenario():
        client = _Client()
        settings = SimpleNamespace(snapshot=lambda: {"retained_lifecycles": 0})
        service = LangGraphLifecycleService(lambda: client, settings=settings)

        await service.enforce_retention()
        assert client.deleted_threads == []

        for runs in client.run_values.values():
            for run in runs:
                run["status"] = "success"
        await service.enforce_retention()
        return client

    client = asyncio.run(scenario())
    assert set(client.deleted_threads) == {"thread-entry", "thread-peer"}
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "input")] == {}
    assert client.store_items[("workflow-lifecycle", "lifecycle-1", "runs")] == {}
