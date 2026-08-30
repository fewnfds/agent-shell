from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import sqlite3
import threading

import pytest

from agent_shell.file_manager import FileManagerService
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.media_response import MainAgentMediaResponse
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.runtime_policy import RuntimePolicyStore


def test_database_initialization_drops_obsolete_runtime_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "state" / "agent-shell.sqlite3"
    database_path.parent.mkdir(parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            "CREATE TABLE api_message_history (id TEXT PRIMARY KEY);"
            "CREATE TABLE api_message_history_outputs (history_id TEXT PRIMARY KEY);"
            "CREATE TABLE agent_session_runs (id TEXT PRIMARY KEY);"
            "CREATE TABLE agent_session_run_outputs (run_id TEXT PRIMARY KEY);"
            "CREATE TABLE media_output_assets (id TEXT PRIMARY KEY);"
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
        "media_output_assets",
    } & tables


def test_media_output_becomes_a_file_manager_user_file(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    repository = FileConfigRepository(data_root)
    policy = RuntimePolicyStore(repository)
    files = FileManagerService(data_root, tmp_path / "runtime" / "tmp", policy)
    response = MainAgentMediaResponse(files, "request-1", policy)

    notification = asyncio.run(
        response.project(
            MediaContentBlock(
                message_id="message-1",
                block_index=0,
                content={
                    "type": "image",
                    "mime_type": "image/png",
                    "base64": base64.b64encode(b"image").decode("ascii"),
                },
            )
        )
    )

    assert notification is not None
    path = notification.rsplit("【", 1)[1].split("】", 1)[0]
    assert path.startswith("data/files/generated/")
    assert path.endswith(".png")
    download = files.prepare_download(path)
    assert download.path.read_bytes() == b"image"
    directory = files.list_directory(path.rsplit("/", 1)[0])
    assert [item["path"] for item in directory["items"]] == [path]

    renamed = files.rename(path, "renamed.png")
    assert renamed["path"].endswith("/renamed.png")
    assert files.delete(str(renamed["path"])) == {
        "path": renamed["path"],
        "deleted": True,
    }


def test_media_response_uses_the_configured_byte_limit(tmp_path: Path) -> None:
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
    files = FileManagerService(data_root, tmp_path / "runtime" / "tmp", policy)
    response = MainAgentMediaResponse(files, "request-1", policy)

    notification = asyncio.run(
        response.project(
            MediaContentBlock(
                message_id="message-1",
                block_index=0,
                content={
                    "type": "image",
                    "mime_type": "image/png",
                    "base64": base64.b64encode(b"12345").decode("ascii"),
                },
            )
        )
    )

    assert notification == "AI发送来了【图片】，但返回内容无法保存。"


def test_cancelled_projection_waits_for_file_save_without_publishing() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingFiles:
        def save_generated_file(
            self, path: str, content: bytes
        ) -> dict[str, object]:
            started.set()
            release.wait(timeout=2)
            finished.set()
            return {"path": path, "kind": "file", "size": len(content)}

    async def run() -> None:
        response = MainAgentMediaResponse(  # type: ignore[arg-type]
            BlockingFiles(), "request-1"
        )
        task = asyncio.create_task(
            response.project(
                MediaContentBlock(
                    message_id="message-1",
                    block_index=0,
                    content={
                        "type": "image",
                        "mime_type": "image/png",
                        "base64": base64.b64encode(b"image").decode("ascii"),
                    },
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

    asyncio.run(run())
