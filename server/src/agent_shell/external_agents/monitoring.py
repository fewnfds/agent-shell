"""Read persisted Antigravity sessions for Lifecycle monitoring.

The runner already owns the durable session records. Monitoring treats those
files as the registry instead of maintaining a second Store projection.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID


def _canonical_uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _antigravity_root(data_root: Path | None, lifecycle_id: str) -> Path | None:
    canonical_lifecycle = _canonical_uuid(lifecycle_id)
    if data_root is None or canonical_lifecycle is None:
        return None
    return Path(data_root) / "antigravity"


def _json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _observation(
    meta: Mapping[str, object],
    *,
    session_id: str,
    error: str | None = None,
) -> dict[str, object]:
    usage = meta.get("usage")
    denied_actions = meta.get("denied_actions")
    return {
        "session_id": session_id,
        "external_agent_id": _text(meta.get("external_agent_id")),
        "external_agent_name": _text(meta.get("external_agent_name")),
        "provider": _text(meta.get("provider")),
        "agent_name": _text(meta.get("agent_name")),
        "status": _text(meta.get("status"), "failed"),
        "conversation_requested": _text(meta.get("conversation_requested")),
        "conversation_id": _optional_text(meta.get("conversation_id")),
        "conversation_reused": (
            meta.get("conversation_reused")
            if isinstance(meta.get("conversation_reused"), bool)
            else None
        ),
        "model": _optional_text(meta.get("model")),
        "effort": _optional_text(meta.get("effort")),
        "started_at": _optional_text(meta.get("started_at")),
        "finished_at": _optional_text(meta.get("finished_at")),
        "duration_ms": (
            meta.get("duration_ms")
            if isinstance(meta.get("duration_ms"), int)
            else None
        ),
        "usage": dict(usage) if isinstance(usage, Mapping) else {},
        "denied_actions": (
            list(denied_actions)
            if isinstance(denied_actions, list)
            else []
        ),
        "error_code": _optional_text(meta.get("error_code")),
        "error_message": _optional_text(meta.get("error_message")),
        "home_path": _optional_text(meta.get("home_path")),
        "workspace_path": _optional_text(meta.get("workspace_path")),
        "event_log": _optional_text(meta.get("event_log")),
        "stderr_log": _optional_text(meta.get("stderr_log")),
        "result_file": _optional_text(meta.get("result_file")),
        "error": error,
    }


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    events: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            if index == len(lines) - 1 and not content.endswith(("\n", "\r")):
                break
            raise
        if not isinstance(value, dict):
            raise ValueError(f"External Agent event line {index + 1} is not an object")
        events.append(value)
    return events


def read_external_agent_sessions(
    data_root: Path | None,
    lifecycle_id: str,
) -> list[dict[str, object]]:
    """Return every persisted External Agent session for one Lifecycle."""

    root = _antigravity_root(data_root, lifecycle_id)
    canonical_lifecycle = _canonical_uuid(lifecycle_id)
    if root is None or canonical_lifecycle is None or not root.is_dir():
        return []

    sessions: list[dict[str, object]] = []
    pattern = f"*/lifecycles/{canonical_lifecycle}/sessions/*/meta.json"
    for meta_path in root.glob(pattern):
        session_id = meta_path.parent.name
        try:
            meta = _json_object(meta_path)
            if meta is None:
                raise ValueError("meta.json must contain a JSON object")
            sessions.append(_observation(meta, session_id=session_id))
        except (OSError, ValueError) as exc:
            sessions.append(
                _observation(
                    {},
                    session_id=session_id,
                    error=f"External Agent session record is invalid: {exc}",
                )
            )
    return sorted(
        sessions,
        key=lambda item: (
            str(item.get("started_at") or ""),
            str(item.get("session_id") or ""),
        ),
    )


def read_external_agent_session(
    data_root: Path | None,
    lifecycle_id: str,
    session_id: str,
) -> dict[str, object] | None:
    """Return one session, its normalized events, and its terminal result."""

    root = _antigravity_root(data_root, lifecycle_id)
    canonical_lifecycle = _canonical_uuid(lifecycle_id)
    canonical_session = _canonical_uuid(session_id)
    if (
        root is None
        or canonical_lifecycle is None
        or canonical_session is None
    ):
        return None

    pattern = (
        f"*/lifecycles/{canonical_lifecycle}/sessions/{canonical_session}/meta.json"
    )
    meta_path = next(iter(root.glob(pattern)), None)
    if meta_path is None:
        return None
    meta = _json_object(meta_path)
    if meta is None:
        raise ValueError("External Agent session meta.json is invalid")
    session_dir = meta_path.parent
    return {
        "session": _observation(meta, session_id=canonical_session),
        "events": _read_events(session_dir / "events.ndjson"),
        "result": _json_object(session_dir / "result.json"),
    }


__all__ = [
    "read_external_agent_session",
    "read_external_agent_sessions",
]
