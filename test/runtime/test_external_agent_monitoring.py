from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from agent_shell.external_agents.monitoring import (
    read_external_agent_session,
    read_external_agent_sessions,
)


def _write_session(
    data_root: Path,
    *,
    lifecycle_id: str,
    session_id: str,
    agent_id: str | None = None,
) -> Path:
    session = (
        data_root
        / "antigravity"
        / (agent_id or str(uuid4()))
        / "lifecycles"
        / lifecycle_id
        / "sessions"
        / session_id
    )
    session.mkdir(parents=True)
    (session / "meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "external_agent_id": agent_id or str(uuid4()),
                "external_agent_name": "Reviewer",
                "provider": "antigravity-cli",
                "agent_name": "reviewer",
                "status": "success",
                "conversation_requested": "new",
                "conversation_id": str(uuid4()),
                "conversation_reused": False,
                "started_at": "2026-09-17T01:00:00+00:00",
                "finished_at": "2026-09-17T01:00:05+00:00",
                "duration_ms": 5000,
                "usage": {"total_tokens": 10},
                "denied_actions": [],
                "home_path": "H:/home",
                "workspace_path": "H:/workspace",
                "event_log": "events.ndjson",
                "stderr_log": "stderr.log",
                "result_file": "result.json",
            }
        ),
        encoding="utf-8",
    )
    (session / "events.ndjson").write_text(
        '{"kind":"text_delta","payload":{"text":"hello"},"at":"t1"}\n'
        '{"kind":"result","payload":{},"at":"t2"}',
        encoding="utf-8",
    )
    (session / "result.json").write_text(
        json.dumps({"status": "success", "response": "hello"}),
        encoding="utf-8",
    )
    return session


def test_reads_sessions_and_ignores_an_incomplete_final_event(
    tmp_path: Path,
) -> None:
    lifecycle_id = str(uuid4())
    session_id = str(uuid4())
    _write_session(
        tmp_path,
        lifecycle_id=lifecycle_id,
        session_id=session_id,
    )

    sessions = read_external_agent_sessions(tmp_path, lifecycle_id)
    detail = read_external_agent_session(tmp_path, lifecycle_id, session_id)

    assert [session["session_id"] for session in sessions] == [session_id]
    assert sessions[0]["status"] == "success"
    assert sessions[0]["external_agent_name"] == "Reviewer"
    assert detail is not None
    assert [event["kind"] for event in detail["events"]] == [
        "text_delta",
        "result",
    ]
    assert detail["result"] == {"status": "success", "response": "hello"}


def test_invalid_session_identity_or_record_is_explicit(tmp_path: Path) -> None:
    lifecycle_id = str(uuid4())
    session_id = str(uuid4())
    session = _write_session(
        tmp_path,
        lifecycle_id=lifecycle_id,
        session_id=session_id,
    )
    (session / "meta.json").write_text("{", encoding="utf-8")

    sessions = read_external_agent_sessions(tmp_path, lifecycle_id)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["status"] == "failed"
    assert sessions[0]["error_code"] is None
    assert str(sessions[0]["error"]).startswith(
        "External Agent session record is invalid:"
    )
    assert read_external_agent_sessions(tmp_path, "not-a-uuid") == []
    assert read_external_agent_session(tmp_path, lifecycle_id, "not-a-uuid") is None
