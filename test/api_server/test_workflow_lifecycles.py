from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import zipfile

from agent_shell.app import create_app
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext
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
                    checkpoint_thread_id=None,
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
                        checkpoint_thread_id=None,
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
        checkpointer = client.post(
            "/api/blocks/checkpointer",
            json={"name": "Managed lifecycle checkpoints"},
        )
        assert checkpointer.status_code == 200, checkpointer.text
        configured_workflow = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                **{
                    key: workflow[key]
                    for key in (
                        "name",
                        "workflow_role",
                        "description",
                        "workflow_event_output_id",
                        "recursion_limit",
                        "execution_timeout_seconds",
                        "max_concurrency",
                    )
                },
                "checkpointer_id": checkpointer.json()["id"],
            },
        )
        assert configured_workflow.status_code == 200, configured_workflow.text
        workflow = configured_workflow.json()
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
        assert root_run["checkpoint_thread_id"]
        assert "thread_id" not in root_run
        assert "checkpoint_available" not in root_run
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

        client.app.state.runtime_diagnostics.observation_error(
            RuntimeError("run-history-detail-sentinel"),
            code="run_history_export_test",
            component="observability",
            context=RuntimeDiagnosticContext(
                lifecycle_id=summary["lifecycle_id"],
                run_id=root_run["run_id"],
            ),
        )

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
                "input.json",
                "agent-invocations.jsonl",
                "model-requests/index.json",
                "background-tasks.jsonl",
                "store-summary.json",
                "store-payloads.jsonl",
                "diagnostics.jsonl",
                f"checkpoints/{root_run['run_id']}.jsonl",
            } <= set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["captured_at"]
            assert manifest["format"] == "agent-shell-run-history-v3"
            assert manifest["includes"]["lifecycle_input"] is True
            assert manifest["includes"]["checkpoint_state"] is True
            assert manifest["includes"]["model_requests"] is True
            assert json.loads(archive.read("input.json"))["messages"] == [
                {"role": "user", "content": "private-run-history-sentinel"}
            ]
            invocations = [
                json.loads(line)
                for line in archive.read("agent-invocations.jsonl").splitlines()
            ]
            assert invocations
            assert any(item["artifact"]["messages"] for item in invocations)
            model_request_index = json.loads(
                archive.read("model-requests/index.json")
            )
            assert model_request_index["capture_layer"] == (
                "langchain.on_chat_model_start"
            )
            assert model_request_index["request_count"] >= 1
            assert len(model_request_index["owners"]) == 1
            model_request_owner = model_request_index["owners"][0]
            assert model_request_owner["agent_type"] == "main_agent"
            assert model_request_owner["agent_id"] == main_agent["id"]
            model_requests = [
                json.loads(line)
                for line in archive.read(
                    f"model-requests/{model_request_owner['path']}"
                ).splitlines()
            ]
            assert model_requests
            assert all(item["run_id"] == root_run["run_id"] for item in model_requests)
            captured_request = model_requests[0]["request"]
            assert any(
                message["type"] == "system"
                for batch in captured_request["message_batches"]
                for message in batch
            )
            assert captured_request["invocation_params"]["tools"]
            checkpoints = [
                json.loads(line)
                for line in archive.read(
                    f"checkpoints/{root_run['run_id']}.jsonl"
                ).splitlines()
            ]
            assert checkpoints
            assert any("state" in item for item in checkpoints)
            diagnostics = [
                json.loads(line)
                for line in archive.read("diagnostics.jsonl").splitlines()
            ]
            assert len(diagnostics) == 1
            diagnostic_path = (
                f"diagnostics/{diagnostics[0]['diagnostic_id']}.log"
            )
            assert diagnostic_path in archive.namelist()
            assert b"run-history-detail-sentinel" in archive.read(diagnostic_path)
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
                "input.json",
                "agent-invocations.jsonl",
                "model-requests/index.json",
                "background-tasks.jsonl",
                "store-summary.json",
                "store-payloads.jsonl",
                "checkpoints.jsonl",
                "diagnostics.jsonl",
            } <= set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["scope"] == "run"
            assert manifest["checkpoint_thread_id"] == root_run[
                "checkpoint_thread_id"
            ]
            assert manifest["includes"]["checkpoint_state"] is True
            run_model_request_index = json.loads(
                archive.read("model-requests/index.json")
            )
            assert run_model_request_index["request_count"] == (
                model_request_index["request_count"]
            )
            assert {
                run_id
                for owner in run_model_request_index["owners"]
                for run_id in owner["run_ids"]
            } == {root_run["run_id"]}
            checkpoints = [
                json.loads(line)
                for line in archive.read("checkpoints.jsonl").splitlines()
            ]
            assert checkpoints
            assert any("state" in item for item in checkpoints)
            diagnostics = [
                json.loads(line)
                for line in archive.read("diagnostics.jsonl").splitlines()
            ]
            assert len(diagnostics) == 1
            diagnostic_path = (
                f"diagnostics/{diagnostics[0]['diagnostic_id']}.log"
            )
            assert diagnostic_path in archive.namelist()
            assert b"run-history-detail-sentinel" in archive.read(diagnostic_path)
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
        assert deleted.json()["deleted_checkpoint_thread_count"] == 1
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
        async def create_lifecycle() -> str:
            return await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="interrupted-request",
                run_id="interrupted-run",
                checkpoint_thread_id=None,
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


def test_lifecycle_without_checkpointer_never_accesses_saver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="No checkpoint history")
        save_linear_workflow_graph(client, workflow, main_agent)
        reply = client.post(
            "/v1/chat/completions",
            json={
                "model": workflow["name"],
                "messages": [{"role": "user", "content": "run"}],
            },
        )
        assert reply.status_code == 200, reply.text
        assert client.app.state.workflow_checkpoints.started is False

        summary = client.get("/api/workflow-lifecycles").json()["items"][0]
        assert summary["checkpoint_count"] == 0
        detail = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
        )
        assert detail.status_code == 200, detail.text
        root_run = detail.json()["runs"][0]
        assert root_run["checkpoint_thread_id"] is None
        assert detail.json()["checkpoints"] == {}
        run_detail = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
            f"/runs/{root_run['run_id']}"
        )
        assert run_detail.status_code == 200, run_detail.text
        assert run_detail.json()["checkpoint_count"] == 0
        assert client.app.state.workflow_checkpoints.started is False

        lifecycle_download = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}/download"
        )
        assert lifecycle_download.status_code == 200, lifecycle_download.text
        with zipfile.ZipFile(BytesIO(lifecycle_download.content)) as archive:
            assert not any(
                name.startswith("checkpoints/") for name in archive.namelist()
            )

        run_download = client.get(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
            f"/runs/{root_run['run_id']}/download"
        )
        assert run_download.status_code == 200, run_download.text
        with zipfile.ZipFile(BytesIO(run_download.content)) as archive:
            assert archive.read("checkpoints.jsonl") == b""
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["checkpoint_thread_id"] is None
        assert client.app.state.workflow_checkpoints.started is False

        deleted = client.delete(
            f"/api/workflow-lifecycles/{summary['lifecycle_id']}"
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_checkpoint_thread_count"] == 0
        assert client.app.state.workflow_checkpoints.started is False


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
                checkpoint_thread_id=None,
                workflow_id="parent-workflow",
                workflow_name="Parent Workflow",
            )

            async def factory(_identity):
                return Execution()

            handle = await client.app.state.background_tasks.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="active-request",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="active-workflow",
                caller_run_depth=0,
                target_id="workflow",
                target_name="Workflow",
                target_graph_sha="graph-sha",
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=True,
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
        child = next(
            run
            for run in runs
            if run["run_kind"] == "workflow" and run["run_depth"] == 1
        )
        assert child["parent_run_id"] == "parent-run"
        assert child["launcher_id"] == "launcher"
        assert child["background_task_id"] == task_id
        assert child["run_depth"] == 1
        assert child["status"] == "completed"
        assert child["checkpoint_thread_id"] is None
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

            return await client.app.state.background_tasks.start_workflow(
                lifecycle_id=lifecycle_id,
                request_id="active-request",
                launcher_run_id="parent-run",
                launcher_id="launcher",
                operation_id="after-delete",
                caller_run_depth=0,
                target_id="workflow",
                target_name="Workflow",
                target_graph_sha="graph-sha",
                checkpoint_thread_id=None,
                cancel_on_upstream_termination=True,
                execution_factory=factory,
            )

        with pytest.raises(AgentRuntimeError) as captured:
            portal.call(start_after_delete)
        assert captured.value.code == "workflow_lifecycle_not_found"


def test_checkpoint_query_failure_is_not_reported_as_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def create_lifecycle() -> str:
            return await client.app.state.workflow_lifecycle.create(
                [{"role": "user", "content": "input"}],
                request_id="checkpoint-query-failure",
                run_id="checkpoint-query-run",
                checkpoint_thread_id="checkpoint-query-thread",
                workflow_id="checkpoint-query-workflow",
                workflow_name="Checkpoint Query Workflow",
            )

        lifecycle_id = portal.call(create_lifecycle)

        async def fail_count(_checkpoint_thread_id: str) -> int:
            raise OSError("checkpoint read failed")

        monkeypatch.setattr(
            client.app.state.workflow_checkpoints,
            "checkpoint_count",
            fail_count,
        )
        response = client.get(
            f"/api/workflow-lifecycles/{lifecycle_id}"
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == (
            "workflow_checkpointer_unavailable"
        )
        entries = client.app.state.runtime_diagnostics.snapshot()["entries"]
        assert any(
            entry["code"] == "workflow_checkpoint_query_failed"
            and entry["lifecycle_id"] == lifecycle_id
            for entry in entries
        )
