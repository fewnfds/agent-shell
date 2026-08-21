from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import zipfile

from agent_shell.app import create_app
from agent_shell.runtime.errors import AgentRuntimeError
from support import ScopedAuthTestClient

from .support import *


def test_lifecycle_list_pages_newest_records_before_building_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def create_records() -> None:
            for index in range(12):
                await client.app.state.workflow_lifecycle.create(
                    [{"role": "user", "content": str(index)}],
                    request_id=f"request-{index:02d}",
                    run_id=f"run-{index:02d}",
                    thread_id=f"thread-{index:02d}",
                    workflow_id=f"workflow-{index:02d}",
                    workflow_name=f"Workflow {index:02d}",
                )
                await asyncio.sleep(0.002)

        portal.call(create_records)
        first = client.get("/api/workflow-lifecycles?page=1&page_size=10")
        second = client.get("/api/workflow-lifecycles?page=2&page_size=10")

    assert first.status_code == 200, first.text
    assert first.json()["total"] == 12
    assert first.json()["total_pages"] == 2
    assert [item["workflow_name"] for item in first.json()["items"]] == [
        f"Workflow {index:02d}" for index in range(11, 1, -1)
    ]
    assert [item["workflow_name"] for item in second.json()["items"]] == [
        "Workflow 01",
        "Workflow 00",
    ]


def test_lifecycle_list_orders_by_creation_not_later_status_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def create_and_finish_oldest() -> None:
            lifecycle_ids: list[str] = []
            for index in range(3):
                lifecycle_ids.append(
                    await client.app.state.workflow_lifecycle.create(
                        [{"role": "user", "content": str(index)}],
                        request_id=f"request-{index}",
                        run_id=f"run-{index}",
                        thread_id=f"thread-{index}",
                        workflow_id=f"workflow-{index}",
                        workflow_name=f"Workflow {index}",
                    )
                )
                await asyncio.sleep(0.002)
            await client.app.state.workflow_lifecycle.finish_parent(
                lifecycle_ids[0],
                "completed",
            )

        portal.call(create_and_finish_oldest)
        listed = client.get(
            "/api/workflow-lifecycles?page=1&page_size=2&query=workflow"
        )

    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 3
    assert [item["workflow_name"] for item in listed.json()["items"]] == [
        "Workflow 2",
        "Workflow 1",
    ]


def test_lifecycle_management_summarizes_and_deletes_dynamic_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dynamic_parent = tmp_path / "dynamic-workspaces"
    dynamic_parent.mkdir()
    with make_client(tmp_path, monkeypatch) as client:
        filesystem = client.post(
            "/api/blocks/filesystem",
            json={
                "name": "Dynamic lifecycle filesystem",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": str(dynamic_parent),
                        "path_origin": "absolute",
                        "lifecycle_mode": "dynamic",
                    }
                ],
            },
        ).json()
        main_agent = create_main_agent(client, filesystem_id=filesystem["id"])
        workflow = create_workflow(
            client,
            name="Managed lifecycle",
        )
        save_linear_workflow_graph(client, workflow, main_agent)

        reply = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [
                    {"role": "user", "content": "private-run-history-sentinel"}
                ],
            },
        )
        assert reply.status_code == 200, reply.text
        listed = client.get("/api/workflow-lifecycles")
        assert listed.status_code == 200, listed.text
        listed_payload = listed.json()
        assert listed_payload["total"] == 1
        assert listed_payload["page_size"] == 10
        assert len(listed_payload["items"]) == 1
        summary = listed_payload["items"][0]
        assert summary["workflow_id"] == workflow["id"]
        assert summary["lifecycle_status"] == "active"
        assert summary["message_count"] == 1
        assert summary["parent_status"] == "completed"
        assert summary["task_count"] == 0
        assert summary["run_count"] == 1
        assert summary["active_run_count"] == 0
        assert summary["failed_run_count"] == 0
        assert summary["observation_status"] == "available"
        assert summary["checkpoint_count"] > 0
        assert summary["dynamic_directory_count"] == 1
        # Lifecycle Store owns the request input, filesystem mapping, and
        # the immutable invocation artifact separately.
        assert summary["store_item_count"] == 3
        detail = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()
        assert len(payload["runs"]) == 1
        root_run = payload["runs"][0]
        assert root_run["run_id"] == summary["parent_run_id"]
        assert root_run["run_kind"] == "workflow"
        assert root_run["status"] == "completed"
        assert root_run["checkpoint_available"] is True
        assert {event["subject_kind"] for event in payload["events"]} >= {
            "run",
            "workflow_node",
            "agent",
            "model",
        }
        node_events = [
            event
            for event in payload["events"]
            if event["subject_kind"] == "workflow_node"
            and event["phase"] == "started"
        ]
        assert node_events
        assert all(event["node_invocation_id"] for event in node_events)
        span_ids = {
            event["span_id"] for event in payload["events"] if event["span_id"]
        }
        assert all(
            not event["parent_span_id"] or event["parent_span_id"] in span_ids
            for event in payload["events"]
        )
        agent_starts = [
            event
            for event in payload["events"]
            if event["subject_kind"] == "agent" and event["phase"] == "started"
        ]
        assert len(agent_starts) == len(node_events)

        run_detail = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
            f"/runs/{root_run['run_id']}"
        )
        assert run_detail.status_code == 200, run_detail.text
        run_payload = run_detail.json()
        assert run_payload["event_count"] == len(payload["events"])
        assert run_payload["checkpoint_count"] == summary["checkpoint_count"]
        assert run_payload["diagnostic_count"] == 0
        assert "events" not in run_payload
        assert "checkpoints" not in run_payload

        downloaded = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}/download"
        )
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers["cache-control"] == "no-store"
        with zipfile.ZipFile(BytesIO(downloaded.content)) as archive:
            assert {
                "manifest.json",
                "lifecycle.json",
                "runs.json",
                "events.jsonl",
                "store-summary.json",
                "diagnostics.jsonl",
                f"checkpoints/{root_run['run_id']}.jsonl",
            } <= set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["captured_at"]
            assert manifest["includes"]["runtime_payloads"] is False
            assert b"private-run-history-sentinel" not in downloaded.content
        run_downloaded = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
            f"/runs/{root_run['run_id']}/download"
        )
        assert run_downloaded.status_code == 200, run_downloaded.text
        with zipfile.ZipFile(BytesIO(run_downloaded.content)) as archive:
            assert {
                "manifest.json",
                "run.json",
                "events.jsonl",
                "checkpoints.jsonl",
                "diagnostics.jsonl",
            } <= set(archive.namelist())
            assert json.loads(archive.read("manifest.json"))["scope"] == "run"
        assert not list(
            (tmp_path / "runtime" / "tmp").glob("workflow-diagnostic-*")
        )
        dynamic_directories = list(dynamic_parent.iterdir())
        assert len(dynamic_directories) == 1
        assert dynamic_directories[0].is_dir()

        deleted = client.delete(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}",
            params={"delete_dynamic_directories": "true"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_dynamic_directories"] is True
        assert list(dynamic_parent.iterdir()) == []
        assert client.get("/api/workflow-lifecycles").json()["items"] == []
        assert client.app.state.workflow_lifecycle.history.get_run(
            summary["parent_run_id"]
        ) is None


def test_lifecycle_restart_cancels_interrupted_parent_and_allows_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_client = make_client(tmp_path, monkeypatch)
    with first_client as client:
        portal = client.portal
        assert portal is not None
        checkpoint_context = client.app.state.workflow_checkpoints.create_context(
            request_id="interrupted-request",
            workflow_id="interrupted-workflow",
            workflow_name="Interrupted Workflow",
            messages_sha="a" * 64,
        )
        async def create_lifecycle() -> str:
            return await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="interrupted-request",
                run_id=str(checkpoint_context.run_id),
                thread_id=checkpoint_context.thread_id,
                workflow_id="interrupted-workflow",
                workflow_name="Interrupted Workflow",
            )

        lifecycle_id = portal.call(create_lifecycle)
        before_restart = client.get(
            f"/api/workflow-lifecycles/{lifecycle_id}"
        )
        assert before_restart.status_code == 200, before_restart.text
        assert before_restart.json()["parent_status"] == "running"

    with ScopedAuthTestClient(create_app()) as client:
        after_restart = client.get(
            f"/api/workflow-lifecycles/{lifecycle_id}"
        )
        assert after_restart.status_code == 200, after_restart.text
        assert after_restart.json()["parent_status"] == "cancelled"
        assert after_restart.json()["runs"][0]["status"] == "interrupted"

        deleted = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert deleted.status_code == 200, deleted.text


def test_lifecycle_delete_rejects_active_background_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None
        release = asyncio.Event()

        class Execution:
            finish_reason = "stop"
            usage: dict[str, int] = {}

            async def stream_text(self):
                await release.wait()
                if False:
                    yield ""

            async def execute(self) -> None:
                async for _part in self.stream_text():
                    pass

        async def start_task():
            lifecycle_id = await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="active-request",
                run_id="parent-run",
                thread_id="parent-thread",
                workflow_id="parent-workflow",
                workflow_name="Parent Workflow",
            )

            async def factory(_identity):
                return Execution()

            handle = await client.app.state.background_tasks.start_agent(
                lifecycle_id=lifecycle_id,
                request_id="active-request",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="active-agent",
                caller_run_depth=0,
                target_id="agent",
                target_name="Agent",
                execution_factory=factory,
            )
            return lifecycle_id, handle.task_id

        lifecycle_id, task_id = portal.call(start_task)
        blocked = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "workflow_lifecycle_active"

        async def finish_task():
            release.set()
            for _ in range(100):
                snapshot = (
                    await client.app.state.background_tasks.check(
                        lifecycle_id,
                        [task_id],
                    )
                )[0]
                if snapshot.runtime_status == "succeeded":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("background task did not finish")

        portal.call(finish_task)
        detail = client.get(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert detail.status_code == 200, detail.text
        runs = detail.json()["runs"]
        assert len(runs) == 2
        child = next(run for run in runs if run["run_kind"] == "agent")
        assert child["parent_run_id"] == "parent-run"
        assert child["launcher_id"] == "launcher"
        assert child["background_task_id"] == task_id
        assert child["run_depth"] == 1
        assert child["status"] == "completed"
        assert child["checkpoint_available"] is False
        still_active = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert still_active.status_code == 409, still_active.text

        portal.call(
            client.app.state.workflow_lifecycle.finish_parent,
            lifecycle_id,
            "completed",
        )
        deleted = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert deleted.status_code == 200, deleted.text

        async def start_after_delete():
            async def factory(_identity):
                return Execution()

            return await client.app.state.background_tasks.start_agent(
                lifecycle_id=lifecycle_id,
                request_id="active-request",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="after-delete",
                caller_run_depth=0,
                target_id="agent",
                target_name="Agent",
                execution_factory=factory,
            )

        with pytest.raises(AgentRuntimeError) as captured:
            portal.call(start_after_delete)
        assert captured.value.code == "workflow_lifecycle_not_found"
