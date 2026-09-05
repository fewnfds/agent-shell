from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from agent_shell.http_surface import is_agent_shell_api_path, is_compat_api_path
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.workflow import admit_workflow_document
from agent_shell.workflow.contracts import WorkflowGraphDocumentV1


MANAGEMENT_TOKEN = "test-management-token"
API_KEY = "test-api-key"


def runtime_workflow_document() -> WorkflowGraphDocumentV1:
    """Return the smallest admitted frozen Workflow document for runtime tests."""

    report, document = admit_workflow_document(
        {
            "definition": {
                "schema_version": 1,
                "state_contract": "agent-shell.workflow.agent-invocations.v1",
                "nodes": [
                    {
                        "id": "start",
                        "type": "start",
                        "type_version": 1,
                        "config": {},
                    },
                    {
                        "id": "end",
                        "type": "end",
                        "type_version": 1,
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "id": "edge",
                        "source": "start",
                        "source_handle": "next",
                        "target": "end",
                        "target_handle": "in",
                    }
                ],
            },
            "layout": {
                "nodes": {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 240, "y": 0},
                },
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        }
    )
    assert report.valid and document is not None
    return document


def configure_scope_tokens(monkeypatch, root: Path) -> None:
    database = SQLiteDatabase(
        root / "data" / "state" / "agent-shell.sqlite3"
    )
    configuration = FileConfigRepository(root / "data")
    configuration.set_secret("AGENT_SHELL_MANAGEMENT_TOKEN", MANAGEMENT_TOKEN)
    store = ApiServerStore(database, configuration)
    if store.api_key() is None:
        store.update_settings(
            api_key_operation="replace",
            api_key=API_KEY,
        )


class ScopedAuthTestClient(TestClient):
    """Attach the matching test Bearer token unless a test supplies its own."""

    def request(self, method, url, **kwargs):
        headers = httpx.Headers(kwargs.get("headers"))
        if "authorization" not in headers:
            path = urlsplit(str(url)).path
            if is_agent_shell_api_path(path):
                headers["Authorization"] = f"Bearer {MANAGEMENT_TOKEN}"
            elif is_compat_api_path(path):
                headers["Authorization"] = f"Bearer {API_KEY}"
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
