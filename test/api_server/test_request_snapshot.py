from __future__ import annotations

from .support import *


def test_snapshot_freezes_workflow_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        workflow = create_workflow(
            client,
            name="Frozen Workflow",
        )

        snapshot = asyncio.run(client.app.state.agent_runtime.capture())
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
            "idle_timeout_seconds": 2.0,
            "max_batch_kb": 64.0,
            "send_interval_seconds": 0.05,
        }
        assert current_snapshot.response_stream_policy().model_dump(mode="json") == {
            "idle_timeout_seconds": 3.5,
            "max_batch_kb": 48.0,
            "send_interval_seconds": 0.15,
        }
