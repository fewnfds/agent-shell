from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agent_shell.runtime.context import AgentRuntimeContext
from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext
from agent_shell.runtime.errors import AgentRuntimeError, decode_server_run_error
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
            component="graph_runtime",
            detail_available=False,
            subject_kind="agent",
            subject_id="agent-one",
            subject_name="Published Main Agent",
            exception_type="AgentRuntimeError",
        )
        response = client.get(
            "/agent-shell/api/event-feed", params=event_feed_params(page_size=100)
        )
        rejected = client.get(
            "/agent-shell/api/event-feed",
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
            "/agent-shell/api/event-feed/system/settings",
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
                component="graph_runtime",
                detail_available=False,
            )
        window = {
            **EVENT_FEED_TEST_WINDOW,
            "source": ["runtime"],
            "level": ["error"],
            "query": marker,
        }
        listed = client.get(
            "/agent-shell/api/event-feed", params={**window, "page_size": 2}
        ).json()
        deleted = client.post("/agent-shell/api/event-feed/delete", json=window)
        remaining = client.get(
            "/agent-shell/api/event-feed", params=event_feed_params(source="runtime", query=marker)
        ).json()

    assert listed["total"] == 3
    assert deleted.json() == {"deleted": 3}
    assert remaining["items"] == []


def test_runtime_diagnostic_settings_have_no_capture_switch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        settings = client.get("/agent-shell/api/runtime-diagnostics")
        removed = client.put(
            "/agent-shell/api/runtime-diagnostics/detail",
            json={"enabled": True},
        )
        listing = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(source="runtime"),
        ).json()

    assert settings.json() == {
        "retention_limit": 20,
    }
    assert removed.status_code == 404
    assert listing["items"] == []


def test_runtime_diagnostic_summary_and_detail_keep_full_exception(
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
                component="graph_runtime",
                context=RuntimeDiagnosticContext(
                    request_id=request_id,
                    lifecycle_id="lifecycle-one",
                    run_id="run-one",
                    thread_id="thread-one",
                    subject_kind="agent",
                    subject_id="agent-one",
                    subject_name="Published Main Agent",
                    workflow_node_id="node-one",
                    node_invocation_id="invocation-one",
                ),
                detail_exception=full_exception,
            )

        listing = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(source="runtime", query=request_id),
        ).json()
        item = listing["items"][0]
        download = client.get(
            f"/agent-shell/api/event-feed/runtime/{item['id']}/download"
        )
        deleted = client.post(
            "/agent-shell/api/event-feed/delete",
            json={
                **EVENT_FEED_TEST_WINDOW,
                "source": ["runtime"],
                "level": [],
                "query": request_id,
            },
        )
        missing = client.get(
            f"/agent-shell/api/event-feed/runtime/{item['id']}/download"
        )

    assert item["download_kind"] == "diagnostic_detail"
    assert item["summary"] == (
        "Published Main Agent · RuntimeError: outer debug failure <- "
        "TypeError: private-debug-detail"
    )
    assert private_detail in item["inline_content"]
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/plain")
    assert download.headers["content-disposition"].endswith('.log"')
    detail_text = download.content.decode("utf-8")
    assert "subject_kind=agent" in detail_text
    assert "run_id=run-one" in detail_text
    assert "TypeError: private-debug-detail" in detail_text
    assert "RuntimeError: outer debug failure" in detail_text
    assert deleted.json() == {"deleted": 1}
    assert missing.status_code == 404
    assert list((tmp_path / "data" / "logs" / "diagnostics").glob("*.log")) == []


def test_provider_error_fact_survives_source_exception_detachment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_provider_response = "<html>gateway body: request was rejected</html>"
    with make_client(tmp_path, monkeypatch) as client:
        diagnostics = client.app.state.runtime_diagnostics
        request = SimpleNamespace(
            runtime=SimpleNamespace(
                context=AgentRuntimeContext(
                    request_id="request-provider-detail",
                    lifecycle_id="lifecycle-provider",
                    main_agent_id="agent-child",
                ),
                execution_info=SimpleNamespace(
                    run_id="run-child",
                    thread_id="thread-child",
                    task_id="task-child",
                    node_attempt=1,
                ),
            )
        )

        def fail(_request):
            raise ValueError(raw_provider_response)

        with pytest.raises(AgentRuntimeError) as captured:
            ProviderErrorBoundaryMiddleware(
                runtime_diagnostics=diagnostics
            ).wrap_model_call(request, fail)

        source_id = captured.value.diagnostic_id
        assert source_id
        source_entry = next(
            entry
            for entry in diagnostics.snapshot()["entries"]
            if entry["diagnostic_id"] == source_id
        )
        assert source_entry["lifecycle_id"] == "lifecycle-provider"
        assert source_entry["run_id"] == "run-child"
        assert source_entry["thread_id"] == "thread-child"
        assert source_entry["subject_kind"] == "agent"
        assert source_entry["subject_id"] == "agent-child"
        source_detail = diagnostics.detail_path(source_id)
        assert source_detail is not None
        assert raw_provider_response in source_detail.read_text(encoding="utf-8")

        # The exception object and its __cause__ no longer exist; only the
        # reference crosses the Server boundary.
        detached = AgentRuntimeError(
            captured.value.code,
            captured.value.message,
            status_code=captured.value.status_code,
            source_exception_type=captured.value.source_exception_type,
            diagnostic_id=source_id,
        )
        transported = decode_server_run_error(str(detached))
        assert transported is not None
        assert transported.diagnostic_id == source_id

        consumer_id = diagnostics.runtime_error(
            transported,
            code=transported.code,
            component="graph_runtime",
            context=RuntimeDiagnosticContext(request_id="request-provider-detail"),
        )

        listing = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(
                source="runtime", query="request-provider-detail"
            ),
        ).json()
        item = next(
            entry for entry in listing["items"] if entry["id"] == consumer_id
        )
        download = client.get(
            f"/agent-shell/api/event-feed/runtime/{item['id']}/download"
        )

    assert item["summary"] == f"ValueError: {raw_provider_response}"
    assert download.status_code == 200
    detail_text = download.content.decode("utf-8")
    assert raw_provider_response in detail_text
    assert f"source_diagnostic_id={source_id}" in detail_text
    assert "source diagnostic:" in detail_text
    assert "ValueError: <html>gateway body: request was rejected</html>" in detail_text


def test_server_error_without_source_fact_marks_it_unavailable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        diagnostics = client.app.state.runtime_diagnostics
        transported = decode_server_run_error(
            str(
                AgentRuntimeError(
                    "official_run_failed",
                    "The official Run failed without an error detail.",
                    status_code=502,
                )
            )
        )
        assert transported is not None
        assert transported.diagnostic_id == ""

        consumer_id = diagnostics.runtime_error(
            transported,
            code=transported.code,
            component="graph_runtime",
            context=RuntimeDiagnosticContext(request_id="request-missing-source"),
        )
        listing = client.get(
            "/agent-shell/api/event-feed",
            params=event_feed_params(
                source="runtime", query="request-missing-source"
            ),
        ).json()
        item = next(
            entry for entry in listing["items"] if entry["id"] == consumer_id
        )
        download = client.get(
            f"/agent-shell/api/event-feed/runtime/{item['id']}/download"
        )

    assert download.status_code == 200
    detail_text = download.content.decode("utf-8")
    assert "source_diagnostic_id=unavailable" in detail_text
    assert "source diagnostic:" not in detail_text


def test_runtime_diagnostic_keeps_structured_entry_when_detail_write_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
            context=RuntimeDiagnosticContext(
                run_id="run-without-detail"
            ),
        )
        entries = client.app.state.runtime_diagnostics.snapshot()["entries"]
        stderr = capsys.readouterr().err

    assert len(entries) == 1
    assert entries[0]["run_id"] == "run-without-detail"
    assert entries[0]["summary"] == "OSError: journal unavailable"
    assert entries[0]["detail_available"] is False
    assert "OSError: diagnostic attachment unavailable" in stderr
