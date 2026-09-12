from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_shell.api.workflow_lifecycles import build_workflow_lifecycle_router
from agent_shell.runtime.langgraph_lifecycle import LangGraphLifecycleNotFound


class _LifecycleService:
    def __init__(self, *, cancelled_runs: int = 0, missing: bool = False) -> None:
        self.cancelled_runs = cancelled_runs
        self.missing = missing
        self.cancelled_lifecycle_ids: list[str] = []

    async def cancel_active(self, lifecycle_id: str) -> int:
        self.cancelled_lifecycle_ids.append(lifecycle_id)
        if self.missing:
            raise LangGraphLifecycleNotFound(lifecycle_id)
        return self.cancelled_runs


class _RequestRuntime:
    def __init__(self, terminated: bool) -> None:
        self.terminated = terminated
        self.terminated_lifecycle_ids: list[str] = []

    def terminate_active_response(self, lifecycle_id: str) -> bool:
        self.terminated_lifecycle_ids.append(lifecycle_id)
        return self.terminated


class _Settings:
    pass


def _client(service: _LifecycleService, runtime: _RequestRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_workflow_lifecycle_router(  # type: ignore[arg-type]
            service,
            _Settings(),
            runtime,
        )
    )
    return TestClient(app)


def test_cancel_workflow_lifecycle_terminates_response_and_official_runs() -> None:
    service = _LifecycleService(cancelled_runs=2)
    runtime = _RequestRuntime(terminated=True)

    response = _client(service, runtime).post(
        "/agent-shell/api/workflow-lifecycles/lifecycle-1/cancel"
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "terminated_response": True,
        "cancelled_run_count": 2,
    }
    assert runtime.terminated_lifecycle_ids == ["lifecycle-1"]
    assert service.cancelled_lifecycle_ids == ["lifecycle-1"]


def test_cancel_workflow_lifecycle_maps_missing_lifecycle_to_404() -> None:
    service = _LifecycleService(missing=True)
    runtime = _RequestRuntime(terminated=False)

    response = _client(service, runtime).post(
        "/agent-shell/api/workflow-lifecycles/missing/cancel"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workflow_lifecycle_not_found"
    assert runtime.terminated_lifecycle_ids == ["missing"]
    assert service.cancelled_lifecycle_ids == ["missing"]
