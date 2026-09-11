from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any, cast

from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.detached_tasks import DetachedTaskManager
from agent_shell.runtime.request_snapshot import (
    LifecycleRunCoordinator,
    RequestRuntimeSnapshot,
)
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_CONFIGURATION_KEY,
    lifecycle_configuration_namespace,
)

from .support import *


def test_snapshot_materializes_runtime_factory_off_event_loop() -> None:
    event_loop_thread_id = 0
    factory_thread_id = 0
    expected_runtime = object()

    def runtime_factory(_store: Any) -> Any:
        nonlocal factory_thread_id
        factory_thread_id = threading.get_ident()
        return expected_runtime

    snapshot = RequestRuntimeSnapshot(
        _workflows=cast(Any, None),
        _agents=cast(Any, None),
        _runtime_factory=runtime_factory,
        _response_stream_policy=ResponseStreamPolicy(),
    )

    async def materialize() -> Any:
        nonlocal event_loop_thread_id
        event_loop_thread_id = threading.get_ident()
        return await snapshot.new_runtime(store=cast(Any, object()))

    assert asyncio.run(materialize()) is expected_runtime
    assert factory_thread_id != event_loop_thread_id


def test_lifecycle_response_termination_only_touches_its_own_coordinator() -> None:
    policy = ResponseStreamPolicy()

    def coordinator(lifecycle_id: str) -> LifecycleRunCoordinator:
        value = LifecycleRunCoordinator(
            _owner=cast(Any, SimpleNamespace()),
            _snapshot=cast(
                Any,
                SimpleNamespace(response_stream_policy=lambda: policy),
            ),
            _detached_tasks=DetachedTaskManager(),
        )
        value._begin_lifecycle(lifecycle_id)
        return value

    first = coordinator("lifecycle-1")
    second = coordinator("lifecycle-2")

    first.terminate_response()

    assert first.response_terminated.is_set() is True
    assert second.response_terminated.is_set() is False


def test_snapshot_freezes_workflow_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(
            client,
            name="Frozen Workflow",
        )
        main_agent = create_main_agent(client)
        save_linear_workflow_graph(client, workflow, main_agent)
        draft = create_workflow(client, name="Excluded Draft")
        draft_agent = client.post(
            f"/agent-shell/api/main-agents/{main_agent['id']}/copy",
            json={"name": "Excluded Agent Draft"},
        ).json()
        manually_corrupted_published_agent = client.post(
            f"/agent-shell/api/main-agents/{main_agent['id']}/copy",
            json={"name": "Manually Corrupted Published Agent"},
        ).json()

        repository = client.app.state.agent_runtime._configuration

        def corrupt_published_agent(config: dict) -> None:
            record = next(
                item
                for item in config["main_agents"]
                if item["id"] == manually_corrupted_published_agent["id"]
            )
            record["enabled"] = True
            record["capability_refs"][0]["block_id"] = (
                "00000000-0000-4000-8000-000000000099"
            )

        repository.update_config(corrupt_published_agent)
        corrupted = next(
            item
            for item in repository.config()["main_agents"]
            if item["id"] == manually_corrupted_published_agent["id"]
        )
        assert corrupted["enabled"] is True

        snapshot = asyncio.run(client.app.state.agent_runtime.capture())
        frozen_configuration = snapshot.lifecycle_configuration(
            graph_kind="workflow",
            resource_id=workflow["id"],
        ).as_store_value()
        assert [
            item["id"]
            for item in frozen_configuration["repository"]["config"]["workflows"]
        ] == [workflow["id"]]
        assert snapshot.workflow_by_id(draft["id"]) is None
        assert snapshot.main_agent_by_id(main_agent["id"]) is not None
        assert snapshot.main_agent_by_id(draft_agent["id"]) is None
        assert (
            snapshot.main_agent_by_id(manually_corrupted_published_agent["id"])
            is not None
        )
        assert [
            item["id"]
            for item in frozen_configuration["repository"]["config"]["main_agents"]
        ] == [main_agent["id"], manually_corrupted_published_agent["id"]]
        assert frozen_configuration["repository"]["config"]["components"]
        assert "provider-test-secret" not in json.dumps(frozen_configuration)
        snapshot_fields = snapshot.__dataclass_fields__
        assert "_response_scheduler" not in snapshot_fields
        assert "_workflow_lifecycle" not in snapshot_fields
        assert "_background_tasks" not in snapshot_fields
        coordinator = client.app.state.agent_runtime.create_lifecycle_coordinator(
            snapshot
        )
        assert "_response_scheduler" in coordinator.__dataclass_fields__
        changed = client.put(
            f"/agent-shell/api/workflows/{workflow['id']}",
            json={
                "name": workflow["name"],
                "description": "Changed after snapshot",
            },
        )
        assert changed.status_code == 200, changed.text

        frozen_workflow = snapshot.workflow_by_name(workflow["name"])
        assert frozen_workflow is not None
        assert frozen_workflow["description"] == workflow["description"]
        next_snapshot = asyncio.run(client.app.state.agent_runtime.capture())
        current_workflow = next_snapshot.workflow_by_name(workflow["name"])
        assert current_workflow is not None
        assert current_workflow["description"] == "Changed after snapshot"

        async def reload_frozen():
            store = InMemoryStore()
            await store.aput(
                lifecycle_configuration_namespace("lifecycle-frozen"),
                LIFECYCLE_CONFIGURATION_KEY,
                frozen_configuration,
                index=False,
            )
            loaded = await client.app.state.agent_runtime.load_lifecycle_snapshot(
                store,
                "lifecycle-frozen",
            )
            with pytest.raises(RuntimeError, match="snapshot is unavailable"):
                await client.app.state.agent_runtime.load_lifecycle_snapshot(
                    store,
                    "missing-lifecycle",
                )
            return loaded

        loaded = asyncio.run(reload_frozen())
        reloaded_workflow = loaded.workflow_by_id(workflow["id"])
        assert reloaded_workflow is not None
        assert reloaded_workflow["description"] == workflow["description"]


def test_snapshot_freezes_response_stream_scheduling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        frozen = asyncio.run(client.app.state.agent_runtime.capture())
        current = client.get("/agent-shell/api/system/settings").json()
        updated = client.put(
            "/agent-shell/api/system/settings",
            json={
                key: current[key]
                for key in (
                    "host",
                    "port",
                    "n_jobs_per_worker",
                    "recursion_limit",
                    "max_concurrency",
                    "debug_port",
                    "allow_remote",
                    "langsmith_tracing_enabled",
                    "langsmith_endpoint",
                    "langsmith_project",
                    "langsmith_workspace_id",
                    "cors_origins",
                    "trusted_proxy_cidrs",
                    "provider_http",
                )
            }
            | {
                "langsmith_api_key": {"operation": "keep"},
                "management_token": {"operation": "preserve"},
                "response_stream_scheduling": {
                    "idle_timeout_seconds": 3.5,
                    "max_batch_kb": 48,
                    "send_interval_seconds": 0.15,
                },
            },
        )
        assert updated.status_code == 200, updated.text
        current_snapshot = asyncio.run(client.app.state.agent_runtime.capture())

        assert frozen.response_stream_policy().model_dump(mode="json") == {
            "idle_timeout_seconds": 10.0,
            "max_batch_kb": 64.0,
            "send_interval_seconds": 0.05,
        }
        assert current_snapshot.response_stream_policy().model_dump(mode="json") == {
            "idle_timeout_seconds": 3.5,
            "max_batch_kb": 48.0,
            "send_interval_seconds": 0.15,
        }
