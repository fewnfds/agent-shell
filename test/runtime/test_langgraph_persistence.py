from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

from langgraph.checkpoint.base import empty_checkpoint
from langgraph_cli.config import validate_config

from agent_shell.langgraph_persistence import (
    configure_persistence,
    generate_checkpointer,
    generate_store,
)


def test_sqlite_checkpoint_and_store_survive_runtime_reopen(tmp_path) -> None:
    runtime_root = tmp_path / "data" / "state" / "langgraph-dev"
    runtime_root.mkdir(parents=True)
    configure_persistence(runtime_root)
    checkpoint_config = {
        "configurable": {
            "thread_id": "thread-1",
            "checkpoint_ns": "",
        }
    }

    async def write_and_read_before_close() -> None:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"messages": ["persisted"]}
        checkpoint["channel_versions"] = {"messages": "1"}
        async with generate_checkpointer() as saver:
            await saver.aput(
                checkpoint_config,
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {"messages": "1"},
            )
            async with generate_checkpointer() as reader:
                saved = await reader.aget_tuple(checkpoint_config)
            assert saved is not None
            assert saved.checkpoint["channel_values"] == {
                "messages": ["persisted"]
            }
        async with generate_store() as store:
            await store.aput(("workflow-lifecycle", "lifecycle-1", "runs"), "run-1", {"thread_id": "thread-1"})
            async with generate_store() as reader:
                item = await reader.aget(
                    ("workflow-lifecycle", "lifecycle-1", "runs"),
                    "run-1",
                )
            assert item is not None
            assert item.value == {"thread_id": "thread-1"}

    async def read() -> None:
        async with generate_checkpointer() as saver:
            saved = await saver.aget_tuple(checkpoint_config)
        assert saved is not None
        assert saved.checkpoint["channel_values"] == {"messages": ["persisted"]}

        async with generate_store() as store:
            item = await store.aget(
                ("workflow-lifecycle", "lifecycle-1", "runs"),
                "run-1",
            )
        assert item is not None
        assert item.value == {"thread_id": "thread-1"}

    asyncio.run(write_and_read_before_close())
    asyncio.run(read())

    assert (runtime_root / "checkpoints.sqlite3").is_file()
    assert (runtime_root / "store.sqlite3").is_file()
    assert not (tmp_path / "data" / "state" / "agent-shell.sqlite3").exists()


def test_sqlite_checkpointer_supports_product_thread_delete(tmp_path) -> None:
    runtime_root = tmp_path / "data" / "state" / "langgraph-dev"
    runtime_root.mkdir(parents=True)
    configure_persistence(runtime_root)
    checkpoint_config = {
        "configurable": {
            "thread_id": "thread-delete",
            "checkpoint_ns": "",
        }
    }

    async def scenario() -> None:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"value": "delete-me"}
        checkpoint["channel_versions"] = {"value": "1"}
        async with generate_checkpointer() as saver:
            await saver.aput(
                checkpoint_config,
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {"value": "1"},
            )
            await saver.adelete_thread("thread-delete")
            async with generate_checkpointer() as reader:
                assert await reader.aget_tuple(checkpoint_config) is None

    asyncio.run(scenario())


def test_locked_config_and_loader_resolve_both_persistence_factories() -> None:
    config_path = (
        Path(__file__).resolve().parents[2]
        / "server"
        / "src"
        / "agent_shell"
        / "langgraph.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validated = validate_config(config)
    checkpointer_path = validated["checkpointer"]["path"]
    store_path = validated["store"]["path"]

    assert checkpointer_path == (
        "agent_shell.langgraph_persistence.generate_checkpointer"
    )
    assert store_path == "agent_shell.langgraph_persistence.generate_store"
    environment = dict(os.environ)
    environment["REDIS_URI"] = "redis://unused.invalid:6379"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from langgraph_api._checkpointer._adapter import "
                "_load_checkpointer; "
                "from langgraph_api.store import _load_store; "
                "from agent_shell.langgraph_persistence import "
                "generate_checkpointer, generate_store; "
                f"assert _load_checkpointer({checkpointer_path!r}) "
                "is generate_checkpointer; "
                f"assert _load_store({store_path!r}) is generate_store"
            ),
        ],
        cwd=config_path.parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
