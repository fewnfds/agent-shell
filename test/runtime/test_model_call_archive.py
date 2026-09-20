from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_shell.runtime.context import AgentRuntimeContext
from agent_shell.runtime.model_call_archive import ModelCallArchiveMiddleware
from agent_shell.storage.model_call_archive import ModelCallArchive


def _model_request() -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(
            context=AgentRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
            ),
            execution_info=SimpleNamespace(
                run_id="run-1",
                thread_id="thread-1",
                task_id="task-1",
                node_attempt=1,
            ),
            server_info=None,
        ),
        model=SimpleNamespace(model_name="gpt-test"),
        system_message=None,
        messages=[],
        tools=[],
        tool_choice=None,
        model_settings={"temperature": 0},
    )


def test_archive_projects_inline_binary_and_round_trips(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    archive.append("lifecycle-1", {"model": {"name": "gpt-test"}})
    archive.append(
        "lifecycle-1",
        {
            "request": {
                "messages": [
                    {
                        "type": "image",
                        "base64": "a" * 5000,
                        "mime_type": "image/png",
                    }
                ]
            }
        },
    )

    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert "gpt-test" in text
    assert "<omitted 5000 chars>" in text
    assert "a" * 100 not in text

    archive.discard("lifecycle-1")
    assert archive.content("lifecycle-1") is None


def test_archive_counts_model_requests_by_run(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    archive.append("lifecycle-1", {"run_id": "run-1"})
    archive.append("lifecycle-1", {"run_id": "run-1"})
    archive.append("lifecycle-1", {"run_id": "run-2"})
    archive.append("lifecycle-1", {})

    assert archive.run_request_counts("lifecycle-1") == {
        "run-1": 2,
        "run-2": 1,
    }


def test_model_call_archive_middleware_records_attempt_identity(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    middleware = ModelCallArchiveMiddleware(archive=archive)
    request = _model_request()
    response = SimpleNamespace(result=[], structured_response=None)

    returned = middleware.wrap_model_call(request, lambda _request: response)

    assert returned is response
    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert '"status":"succeeded"' in text
    assert '"run_id":"run-1"' in text
    assert '"task_id":"task-1"' in text
    assert '"name":"gpt-test"' in text


def test_model_call_archive_middleware_records_failed_attempt(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    middleware = ModelCallArchiveMiddleware(archive=archive)

    def fail(_request):
        raise RuntimeError("provider rejected the request")

    with pytest.raises(RuntimeError):
        middleware.wrap_model_call(_model_request(), fail)

    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert '"status":"failed"' in text
    assert "provider rejected the request" in text
