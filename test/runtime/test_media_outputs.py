from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import sqlite3
import threading

import pytest

from agent_shell.runtime.media_response import MainAgentMediaResponse
from agent_shell.runtime.output_stream import MainAgentMediaBlock
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.media_outputs import MediaOutputStore, MediaProjection
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.runtime_policy import RuntimePolicyStore


def test_database_initialization_drops_obsolete_history_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "state" / "agent-shell.sqlite3"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            "CREATE TABLE api_message_history (id TEXT PRIMARY KEY);"
            "CREATE TABLE api_message_history_outputs (history_id TEXT PRIMARY KEY);"
            "CREATE TABLE agent_session_runs (id TEXT PRIMARY KEY);"
            "CREATE TABLE agent_session_run_outputs (run_id TEXT PRIMARY KEY);"
        )

    database = SQLiteDatabase(database_path)
    with database.transaction() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert not {
        "api_message_history",
        "api_message_history_outputs",
        "agent_session_runs",
        "agent_session_run_outputs",
    } & tables


def test_failed_file_cleanup_keeps_asset_index_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = SQLiteDatabase(tmp_path / "data" / "state" / "agent-shell.sqlite3")
    store = MediaOutputStore(database, tmp_path / "data" / "media" / "outputs")
    projection = store.persist(
        request_id="request-1",
        message_id="message-1",
        block_index=0,
        block={
            "type": "image",
            "mime_type": "image/png",
            "base64": base64.b64encode(b"image").decode("ascii"),
        },
    )
    assert projection.asset is not None
    asset_id = str(projection.asset["id"])
    target = tmp_path / str(projection.asset["relative_path"])
    original_unlink = Path.unlink

    def fail_target_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.resolve() == target.resolve():
            raise PermissionError("test cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_target_unlink)
    store.finish_request("request-1")

    with database.transaction() as connection:
        retained = connection.execute(
            "SELECT id FROM media_output_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    assert retained is not None
    assert target.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    store.cleanup_unreferenced()

    with database.transaction() as connection:
        removed = connection.execute(
            "SELECT id FROM media_output_assets WHERE id = ?", (asset_id,)
        ).fetchone()
    assert removed is None
    assert not target.exists()


def test_media_output_store_uses_the_configured_byte_limit(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    repository = FileConfigRepository(data_root)
    policy = RuntimePolicyStore(repository)
    current = policy.public()
    update = {
        key: value
        for key, value in current.items()
        if key not in {"defaults", "minimums", "configurable"}
    }
    update["media_output_bytes"] = 4
    policy.update(update)
    database = SQLiteDatabase(data_root / "state" / "agent-shell.sqlite3")
    store = MediaOutputStore(database, data_root / "media" / "outputs", policy)

    projection = store.persist(
        request_id="request-1",
        message_id="message-1",
        block_index=0,
        block={
            "type": "image",
            "mime_type": "image/png",
            "base64": base64.b64encode(b"12345").decode("ascii"),
        },
    )

    assert projection.asset is None
    assert projection.structured_block["reason"] == "content_invalid"


def test_cancelled_projection_waits_for_persistence_without_publishing() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingStore:
        def persist(self, **_kwargs: object) -> MediaProjection:
            started.set()
            release.wait(timeout=2)
            finished.set()
            return MediaProjection(
                notification="saved",
                structured_block={"type": "image"},
                asset={"id": "asset-1"},
            )

    async def run() -> None:
        response = MainAgentMediaResponse(BlockingStore(), "request-1")  # type: ignore[arg-type]
        task = asyncio.create_task(
            response.project(
                MainAgentMediaBlock(
                    timestamp="2026-01-01T00:00:00+00:00",
                    namespace="main_agent",
                    agent_name="main_agent",
                    node="model",
                    message_id="message-1",
                    block_index=0,
                    content={"type": "image"},
                )
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert response.assets == []

    asyncio.run(run())
