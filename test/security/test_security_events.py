from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_shell.app import create_app
from agent_shell import security_events
from agent_shell.security_events import SecurityEventLogger
from support import ScopedAuthTestClient, configure_scope_tokens


def _event_feed_params(**filters: object) -> dict[str, object]:
    return {
        "started_at": "2000-01-01T00:00:00+00:00",
        "ended_at": "2100-01-01T00:00:00+00:00",
        **filters,
    }


@pytest.fixture(autouse=True)
def clean_agent_shell_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.upper().startswith("AGENT_SHELL_"):
            monkeypatch.delenv(key, raising=False)


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    configure_scope_tokens(monkeypatch, tmp_path)
    return tmp_path / "data"


def _model(credential: str | None) -> dict:
    return {
        "name": "Event model",
        "provider": "openai",
        "base_url": "https://provider.example/v1",
        "credential": credential,
        "model": "event-model",
        "provider_settings": {
            "temperature": 0.2,
            "max_completion_tokens": 1024,
        },
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
    }


def test_lifecycle_configuration_events_and_model_secrets_are_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _configure(monkeypatch, tmp_path)
    secret = "event-provider-secret-sentinel"
    replacement = "replacement-provider-secret-sentinel"
    request_id = "event_req-123"

    with ScopedAuthTestClient(create_app()) as client:
        created = client.post(
            "/api/model-connections",
            json=_model(secret),
            headers={"X-Request-ID": request_id},
        )
        assert created.status_code == 200
        block_id = created.json()["id"]
        rotated = client.put(
            f"/api/model-connections/{block_id}",
            json=_model(replacement),
            headers={"X-Request-ID": request_id},
        )
        assert rotated.status_code == 200
        configured = client.post(
            "/api/blocks/system-prompt",
            json={"name": "Event prompt", "system_prompt": "Be precise."},
            headers={"X-Request-ID": request_id},
        )
        assert configured.status_code == 200

    log_path = runtime / "logs" / "security-events.jsonl"
    raw = log_path.read_text(encoding="utf-8")
    assert secret not in raw
    assert replacement not in raw
    assert "Event model" not in raw
    assert "provider.example" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    names = [record["event"] for record in records]
    assert "security_configuration_loaded" in names
    assert "service_started" in names
    assert "configuration_updated" in names
    assert "cache_invalidated" not in names
    assert names[-1] == "service_stopped"
    request_records = [
        record
        for record in records
        if record["event"] == "configuration_updated"
    ]
    assert request_records
    assert all(record["request_id"] == request_id for record in request_records)
    assert all(set(record) == {"timestamp", "event", "request_id", "actor", "metadata"} for record in records)


def test_event_logger_reuses_redaction_and_rejects_unregistered_metadata(
    tmp_path: Path,
) -> None:
    logger = SecurityEventLogger(tmp_path / "logs")
    logger.emit(
        "service_stopped",
        {
            "reason": (
                "Bearer audit-token-sentinel at "
                "C:\\Users\\private\\runtime\\trace.txt"
            )
        },
    )
    with pytest.raises(ValueError, match="unsupported metadata fields"):
        logger.emit(
            "configuration_updated",
            {
                "action": "updated",
                "entity": "block",
                "entity_id": "safe-id",
                "capability_type": "model-requirement",
                "api_key": "unregistered-secret-sentinel",
            },
        )

    raw = logger.path.read_text(encoding="utf-8")
    assert "audit-token-sentinel" not in raw
    assert "Users" not in raw
    assert "unregistered-secret-sentinel" not in raw
    assert logger.directory_permission.enforced is True
    assert logger.file_permission.enforced is True


def test_event_persistence_failure_does_not_reverse_committed_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _configure(monkeypatch, tmp_path)
    private_detail = str(tmp_path / "private" / "security-events.jsonl")

    def fail_rollover(*_args, **_kwargs):
        raise OSError(private_detail)

    monkeypatch.setattr(
        security_events._ReportingRotatingFileHandler,
        "shouldRollover",
        fail_rollover,
    )

    with ScopedAuthTestClient(create_app()) as client:
        created = client.post(
            "/api/blocks/system-prompt",
            json={"name": "Committed prompt", "system_prompt": "Persist this."},
        )
        assert created.status_code == 200
        block_id = created.json()["id"]
        assert [
            item["id"]
            for item in client.get("/api/blocks/system-prompt").json()
        ] == [block_id]

        diagnostics = client.get(
            "/api/event-feed",
            params=_event_feed_params(
                source="runtime", query="security_event_record_failed"
            ),
        ).json()
        assert any(
            json.loads(item["inline_content"])["entry"]["code"]
            == "security_event_record_failed"
            for item in diagnostics["items"]
            if item["inline_content"] is not None
        )
        assert private_detail not in json.dumps(diagnostics, ensure_ascii=False)

    assert not (runtime / "logs" / "runtime.log").exists()


def test_event_log_enforces_one_file_without_backups(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    Path(logs_dir / "security-events.jsonl.1").write_text("old backup", encoding="utf-8")
    Path(logs_dir / "security-events.jsonl.2").write_text("old backup", encoding="utf-8")
    logger = SecurityEventLogger(logs_dir, max_bytes=512)
    for index in range(30):
        logger.emit(
            "configuration_updated",
            {
                "action": "updated",
                "entity": "block",
                "entity_id": f"block-{index:02d}",
                "capability_type": "model-requirement",
            },
        )

    assert 0 < logger.path.stat().st_size <= 512
    assert not Path(str(logger.path) + ".1").exists()
    assert not Path(str(logger.path) + ".2").exists()
    records = [json.loads(line) for line in logger.path.read_text(encoding="utf-8").splitlines()]
    assert records
    assert all(record["event"] == "configuration_updated" for record in records)


def test_event_feed_filters_persisted_system_operations_and_management_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, tmp_path)
    operation_request_id = "system-operation-123"
    error_request_id = "system-error-456"

    with ScopedAuthTestClient(create_app()) as client:
        created = client.post(
            "/api/blocks/system-prompt",
            json={"name": "Event prompt", "system_prompt": "Be precise."},
            headers={"X-Request-ID": operation_request_id},
        )
        rejected = client.post(
            "/api/blocks/system-prompt",
            json={
                "name": "Invalid prompt",
                "system_prompt": "",
                "credential": "must-never-enter-event-feed",
            },
            headers={"X-Request-ID": error_request_id},
        )
        operation_logs = client.get(
            "/api/event-feed",
            params=_event_feed_params(source="system", query=operation_request_id),
        )
        error_logs = client.get(
            "/api/event-feed",
            params=_event_feed_params(
                source="system",
                level="error",
                query="configuration_validation_failed",
            ),
        )

    assert created.status_code == 200
    assert rejected.status_code == 422
    assert operation_logs.status_code == 200
    operation = operation_logs.json()
    assert len(operation["items"]) == 1
    operation_entry = json.loads(operation["items"][0]["inline_content"])["entry"]
    assert operation_entry["event"] == "configuration_updated"
    assert operation["items"][0]["request_id"] == operation_request_id
    assert error_logs.status_code == 200
    error = error_logs.json()
    expected_issue_count = len(
        rejected.json()["detail"]["validation"]["issues"]
    )
    assert len(error["items"]) == 1
    error_entry = json.loads(error["items"][0]["inline_content"])["entry"]
    assert error_entry["event"] == "management_request_failed"
    assert error["items"][0]["request_id"] == error_request_id
    error_metadata = error_entry["metadata"]
    assert {key: error_metadata[key] for key in (
        "code", "issue_count", "method", "path", "status_code"
    )} == {
        "code": "configuration_validation_failed",
        "issue_count": expected_issue_count,
        "method": "POST",
        "path": "/api/blocks/system-prompt",
        "status_code": 422,
    }
    assert "must-never-enter-event-feed" not in json.dumps(error)


def test_authentication_failures_are_queryable_without_recording_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, tmp_path)
    invalid_credential = "invalid-management-token-sentinel"
    request_id = "system-auth-789"

    with ScopedAuthTestClient(create_app()) as client:
        rejected = client.get(
            "/api/event-feed",
            headers={
                "Authorization": f"Bearer {invalid_credential}",
                "X-Request-ID": request_id,
            },
        )
        logs = client.get(
            "/api/event-feed",
            params=_event_feed_params(source="system", query=request_id),
        )

    assert rejected.status_code == 401
    assert logs.status_code == 200
    payload = logs.json()
    assert len(payload["items"]) == 1
    auth_entry = json.loads(payload["items"][0]["inline_content"])["entry"]
    assert auth_entry["event"] == "authentication_failed"
    auth_metadata = auth_entry["metadata"]
    assert {key: auth_metadata[key] for key in (
        "code", "required_scope", "status_code"
    )} == {
        "code": "invalid_api_key",
        "required_scope": "management",
        "status_code": 401,
    }
    assert invalid_credential not in json.dumps(payload)
