from __future__ import annotations

from pathlib import Path

import pytest

from agent_shell.contracts import FilesystemBlock
from support import runtime_workflow_document

from .support import make_client


async def _create_lifecycle(client, suffix: str, *, capture: bool = True) -> str:
    return await client.app.state.workflow_lifecycle.create(
        [{"role": "user", "content": f"input-{suffix}"}],
        request_id=f"request-{suffix}",
        run_id=f"run-{suffix}",
        checkpoint_thread_id=None,
        workflow_id=f"workflow-{suffix}",
        workflow_name=f"Workflow {suffix}",
        workflow_document=runtime_workflow_document(),
        monitoring_capture_enabled=capture,
    )


def test_lifecycle_catalog_exposes_registry_summary_and_generic_detail_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None
        lifecycle_id = portal.call(_create_lifecycle, client, "catalog")

        def monitoring_unavailable(_run_id: str):
            raise OSError("monitoring store unavailable")

        monkeypatch.setattr(
            client.app.state.workflow_lifecycle.monitoring,
            "status",
            monitoring_unavailable,
        )

        catalog = client.get("/api/workflow-lifecycles")
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["total"] == 1
        item = catalog.json()["items"][0]
        assert item["lifecycle_id"] == lifecycle_id
        assert item["root_run_id"] == "run-catalog"
        assert item["root_status"] == "pending"
        assert item["run_count"] == 1
        assert item["active_run_count"] == 1
        assert item["monitoring_capture_enabled"] is True

        filtered = client.get(
            "/api/workflow-lifecycles",
            params={"query": "workflow catalog"},
        )
        assert filtered.status_code == 200, filtered.text
        assert [entry["lifecycle_id"] for entry in filtered.json()["items"]] == [
            lifecycle_id
        ]

        for path in (
            f"/api/workflow-lifecycles/{lifecycle_id}",
            f"/api/workflow-lifecycles/{lifecycle_id}/events",
            f"/api/workflow-lifecycles/{lifecycle_id}/runs/run-catalog",
            f"/api/workflow-lifecycles/{lifecycle_id}/download",
            f"/api/workflow-lifecycles/{lifecycle_id}/runs/run-catalog/download",
        ):
            response = client.get(path)
            assert response.status_code == 503, response.text
            assert response.json()["detail"]["code"] == (
                "runtime_monitoring_read_model_unavailable"
            )

        missing = client.get("/api/workflow-lifecycles/missing")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == (
            "workflow_lifecycle_not_found"
        )


def test_run_detail_and_download_validate_lifecycle_ownership_before_tbd_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None
        first_id = portal.call(_create_lifecycle, client, "first")
        second_id = portal.call(_create_lifecycle, client, "second")

        for suffix in ("", "/download"):
            response = client.get(
                f"/api/workflow-lifecycles/{first_id}/runs/run-second{suffix}"
            )
            assert response.status_code == 404, response.text
            assert response.json()["detail"]["code"] == "workflow_run_not_found"

        own = client.get(
            f"/api/workflow-lifecycles/{second_id}/runs/run-second"
        )
        assert own.status_code == 503


def test_explicit_delete_rejects_active_run_and_preserves_user_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None
        dynamic_root = tmp_path / "data" / "dynamic"
        dynamic_root.mkdir(parents=True)
        filesystem = FilesystemBlock.model_validate(
            {
                "name": "Lifecycle workspace",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": str(dynamic_root),
                        "path_origin": "absolute",
                        "lifecycle_mode": "dynamic",
                    }
                ],
            }
        )

        async def prepare() -> tuple[str, Path]:
            lifecycle_id = await _create_lifecycle(client, "delete")
            routes = await client.app.state.workflow_lifecycle.resolve_mapped_directories(
                lifecycle_id,
                "filesystem",
                filesystem,
            )
            return lifecycle_id, routes["/workspace/"]

        lifecycle_id, dynamic_directory = portal.call(prepare)
        (dynamic_directory / "result.txt").write_text("keep", encoding="utf-8")

        active = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert active.status_code == 409, active.text
        assert active.json()["detail"]["code"] == "workflow_lifecycle_active"

        async def finish() -> None:
            service = client.app.state.workflow_lifecycle
            assert service.finish_run("run-delete", status="completed")

        portal.call(finish)
        deleted = client.delete(f"/api/workflow-lifecycles/{lifecycle_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {
            "ok": True,
            "deleted_checkpoint_thread_count": 0,
        }
        assert dynamic_directory.is_dir()
        assert (dynamic_directory / "result.txt").read_text(
            encoding="utf-8"
        ) == "keep"

def test_bulk_delete_uses_full_query_and_skips_active_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        portal = client.portal
        assert portal is not None

        async def prepare() -> tuple[str, str, str]:
            terminal_id = await _create_lifecycle(client, "matching-terminal")
            active_id = await _create_lifecycle(client, "matching-active")
            other_id = await _create_lifecycle(client, "other")
            service = client.app.state.workflow_lifecycle
            assert service.finish_run(
                "run-matching-terminal",
                status="completed",
            )
            assert service.finish_run("run-other", status="completed")
            return terminal_id, active_id, other_id

        terminal_id, active_id, other_id = portal.call(prepare)
        response = client.post(
            "/api/workflow-lifecycles/delete",
            json={"query": "matching"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "matched": 2,
            "deleted": 1,
            "skipped_active": 1,
            "deleted_checkpoint_thread_count": 0,
        }
        assert client.get(
            f"/api/workflow-lifecycles/{terminal_id}"
        ).status_code == 404
        assert client.get(
            f"/api/workflow-lifecycles/{active_id}"
        ).status_code == 503
        assert client.get(
            f"/api/workflow-lifecycles/{other_id}"
        ).status_code == 503
