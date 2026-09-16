from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_shell.api.runtime_monitoring import build_runtime_monitoring_router
from agent_shell.runtime.langgraph_lifecycle import (
    LangGraphExternalAgentSessionNotFound,
)


class _Service:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing

    async def snapshot(self, lifecycle_id: str) -> dict:
        return {
            "lifecycle_id": lifecycle_id,
            "threads": [],
            "external_agent_sessions": [],
        }

    async def external_agent_session(self, lifecycle_id: str, session_id: str) -> dict:
        if self.missing:
            raise LangGraphExternalAgentSessionNotFound(session_id)
        return {
            "session": {
                "session_id": session_id,
                "status": "success",
            },
            "events": [{"kind": "text_delta", "payload": {"text": "hello"}}],
            "result": {"status": "success", "response": "hello"},
        }


def _client(service: _Service) -> TestClient:
    app = FastAPI()
    app.include_router(build_runtime_monitoring_router(service))  # type: ignore[arg-type]
    return TestClient(app)


def test_external_agent_session_endpoint_returns_persisted_events() -> None:
    response = _client(_Service()).get(
        "/agent-shell/api/workflow-lifecycles/lifecycle-1/monitoring"
        "/external-agents/session-1/events"
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["kind"] == "text_delta"
    assert response.json()["result"]["response"] == "hello"


def test_external_agent_session_endpoint_maps_missing_session_to_404() -> None:
    response = _client(_Service(missing=True)).get(
        "/agent-shell/api/workflow-lifecycles/lifecycle-1/monitoring"
        "/external-agents/missing/events"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "external_agent_session_not_found"
