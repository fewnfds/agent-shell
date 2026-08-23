from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.limits import ProviderErrorBoundaryMiddleware

from .support import *


def test_event_feed_exposes_only_supported_sources(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.app.state.security_events.emit(
            "configuration_updated",
            {"action": "updated", "entity": "test", "entity_id": "one"},
        )
        client.app.state.runtime_diagnostic_store.add(
            diagnostic_id="1" * 32,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            severity="error",
            request_id="request-runtime",
            code="runtime_failed",
            summary="request failed",
            component="workflow_runtime",
            detail_available=False,
            parent_workflow_id="workflow-parent",
            parent_workflow_name="Published Workflow",
            subject_kind="agent",
            subject_id="agent-one",
            subject_name="Published Main Agent",
            exception_type="AgentRuntimeError",
        )
        response = client.get(
            "/api/event-feed", params=event_feed_params(page_size=100)
        )
        rejected = client.get(
            "/api/event-feed",
            params=event_feed_params(source="api_call"),
        )

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["source"] for item in items} == {"system", "runtime"}
    assert all(
        set(item)
        == {
            "id",
            "source",
            "occurred_at",
            "level",
            "request_id",
            "summary",
            "inline_content",
            "matched_in_content",
            "download_kind",
        }
        for item in items
    )
    assert rejected.status_code == 422


def test_system_log_settings_reject_boolean_size(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        rejected = client.put(
            "/api/event-feed/system/settings",
            json={"max_size_mib": True},
        )

    assert rejected.status_code == 422


def test_event_feed_deletes_filtered_runtime_records_across_pages(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "delete-every-matching-log"
    with make_client(tmp_path, monkeypatch) as client:
        store = client.app.state.runtime_diagnostic_store
        for index in range(3):
            store.add(
                diagnostic_id=f"{index + 1:032x}",
                occurred_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=index)
                ).isoformat(),
                severity="error",
                request_id=f"request-{index}",
                code="runtime_failed",
                summary=marker,
                component="workflow_runtime",
                detail_available=False,
            )
        window = {
            **EVENT_FEED_TEST_WINDOW,
            "source": ["runtime"],
            "level": ["error"],
            "query": marker,
        }
        listed = client.get(
            "/api/event-feed", params={**window, "page_size": 2}
        ).json()
        deleted = client.post("/api/event-feed/delete", json=window)
        remaining = client.get(
            "/api/event-feed", params=event_feed_params(source="runtime", query=marker)
        ).json()

    assert listed["total"] == 3
    assert deleted.json() == {"deleted": 3}
    assert remaining["items"] == []


def test_runtime_diagnostic_settings_have_no_capture_switch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        settings = client.get("/api/runtime-diagnostics")
        removed = client.put(
            "/api/runtime-diagnostics/detail",
            json={"enabled": True},
        )
        listing = client.get(
            "/api/event-feed",
            params=event_feed_params(source="runtime"),
        ).json()

    assert settings.json() == {
        "retention_limit": 20,
    }
    assert removed.status_code == 404
    assert listing["items"] == []


def test_runtime_diagnostic_detail_keeps_full_exception_out_of_summary(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_id = "request-full-debug"
    private_detail = "private-debug-detail"
    with make_client(tmp_path, monkeypatch) as client:
        try:
            try:
                raise TypeError(private_detail)
            except TypeError as cause:
                raise RuntimeError("outer debug failure") from cause
        except RuntimeError as full_exception:
            client.app.state.runtime_diagnostics.runtime_error(
                AgentRuntimeError(
                    "agent_execution_failed",
                    "The Agent failed during graph execution.",
                    status_code=502,
                ),
                code="agent_execution_failed",
                component="workflow_runtime",
                context=RuntimeDiagnosticContext(
                    request_id=request_id,
                    lifecycle_id="lifecycle-one",
                    run_id="run-one",
                    thread_id="thread-one",
                    parent_workflow_id="workflow-parent",
                    parent_workflow_name="Published Workflow",
                    subject_kind="agent",
                    subject_id="agent-one",
                    subject_name="Published Main Agent",
                    workflow_node_id="node-one",
                    node_invocation_id="invocation-one",
                ),
                detail_exception=full_exception,
            )

        listing = client.get(
            "/api/event-feed",
            params=event_feed_params(source="runtime", query=request_id),
        ).json()
        item = listing["items"][0]
        download = client.get(
            f"/api/event-feed/runtime/{item['id']}/download"
        )
        deleted = client.post(
            "/api/event-feed/delete",
            json={
                **EVENT_FEED_TEST_WINDOW,
                "source": ["runtime"],
                "level": [],
                "query": request_id,
            },
        )
        missing = client.get(
            f"/api/event-feed/runtime/{item['id']}/download"
        )

    assert item["download_kind"] == "diagnostic_detail"
    assert item["summary"] == (
        "Published Main Agent · The Agent failed during graph execution."
    )
    assert private_detail not in item["inline_content"]
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/plain")
    assert download.headers["content-disposition"].endswith('.log"')
    detail_text = download.content.decode("utf-8")
    assert "parent_workflow_name=Published Workflow" in detail_text
    assert "run_id=run-one" in detail_text
    assert "TypeError: private-debug-detail" in detail_text
    assert "RuntimeError: outer debug failure" in detail_text
    assert deleted.json() == {"deleted": 1}
    assert missing.status_code == 404
    assert list((tmp_path / "data" / "logs" / "diagnostics").glob("*.log")) == []


def test_provider_error_detail_is_management_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_provider_response = "<html>gateway body: request was rejected</html>"
    with make_client(tmp_path, monkeypatch) as client:
        def fail(_request):
            raise ValueError(raw_provider_response)

        with pytest.raises(AgentRuntimeError) as captured:
            ProviderErrorBoundaryMiddleware().wrap_model_call(None, fail)
        client.app.state.runtime_diagnostics.runtime_error(
            captured.value,
            code=captured.value.code,
            component="workflow_runtime",
            context=RuntimeDiagnosticContext(request_id="request-provider-detail"),
        )

        listing = client.get(
            "/api/event-feed",
            params=event_feed_params(
                source="runtime", query="request-provider-detail"
            ),
        ).json()
        item = listing["items"][0]
        download = client.get(
            f"/api/event-feed/runtime/{item['id']}/download"
        )

    assert raw_provider_response not in json.dumps(listing)
    assert item["summary"] == "The model provider request failed."
    assert download.status_code == 200
    assert raw_provider_response in download.content.decode("utf-8")


def test_runtime_diagnostic_keeps_structured_entry_when_detail_write_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:

        def fail_detail_write(*_args, **_kwargs):
            raise OSError("diagnostic attachment unavailable")

        monkeypatch.setattr(
            client.app.state.runtime_diagnostic_details,
            "write",
            fail_detail_write,
        )
        client.app.state.runtime_diagnostics.observation_error(
            OSError("journal unavailable"),
            code="workflow_run_event_record_failed",
            component="observability",
            context=RuntimeDiagnosticContext(run_id="run-without-detail"),
        )
        entries = client.app.state.runtime_diagnostics.snapshot()["entries"]

    assert len(entries) == 1
    assert entries[0]["run_id"] == "run-without-detail"
    assert entries[0]["detail_available"] is False
