from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from collections.abc import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_shell.runtime.json_values import json_safe
from agent_shell.storage.database import SQLiteFile


class WorkflowCheckpointService:
    """Own official Workflow checkpoints; runtime facts have separate owners."""

    def __init__(self, database: SQLiteFile) -> None:
        self._database = database
        self._context: AbstractAsyncContextManager[AsyncSqliteSaver] | None = None
        self._checkpointer: AsyncSqliteSaver | None = None
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._checkpointer is not None

    async def require_checkpointer(self) -> AsyncSqliteSaver:
        if self._checkpointer is not None:
            return self._checkpointer
        async with self._lock:
            if self._checkpointer is not None:
                return self._checkpointer
            self._database.prepare()
            context = AsyncSqliteSaver.from_conn_string(str(self._database.path))
            checkpointer: AsyncSqliteSaver | None = None
            try:
                checkpointer = await context.__aenter__()
                await checkpointer.setup()
            except BaseException as exc:
                if checkpointer is not None:
                    await context.__aexit__(type(exc), exc, exc.__traceback__)
                raise
            self._context = context
            self._checkpointer = checkpointer
            return checkpointer

    async def close(self) -> None:
        async with self._lock:
            context = self._context
            self._context = None
            self._checkpointer = None
            if context is not None:
                await context.__aexit__(None, None, None)

    async def checkpoint_history(
        self, thread_id: str, *, limit: int | None = 100
    ) -> list[dict[str, object]]:
        return [
            item
            async for item in self.iter_checkpoint_history(
                thread_id,
                limit=limit,
            )
        ]

    async def latest_state(self, thread_id: str) -> dict[str, object] | None:
        """Read the latest persisted root checkpoint through the public API."""

        if self._checkpointer is None and not self._database.path.exists():
            return None
        checkpointer = await self.require_checkpointer()
        item = await checkpointer.aget_tuple(
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                }
            }
        )
        if item is None:
            return None
        configurable = item.config.get("configurable", {})
        checkpoint = item.checkpoint
        metadata = item.metadata or {}
        return {
            "checkpoint_id": str(configurable.get("checkpoint_id", "")),
            "checkpoint_ns": str(configurable.get("checkpoint_ns", "")),
            "created_at": str(checkpoint.get("ts", "")),
            "source": str(metadata.get("source", "")),
            "step": metadata.get("step"),
            "pending_write_count": len(item.pending_writes or ()),
            "state": json_safe(checkpoint.get("channel_values", {})),
        }

    async def iter_checkpoint_history(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        include_state: bool = False,
    ) -> AsyncIterator[dict[str, object]]:
        checkpointer = await self.require_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}
        async for item in checkpointer.alist(config, limit=limit):
            configurable = item.config.get("configurable", {})
            checkpoint = item.checkpoint
            metadata = item.metadata or {}
            channels = checkpoint.get("channel_values", {})
            record: dict[str, object] = {
                "checkpoint_id": str(configurable.get("checkpoint_id", "")),
                "checkpoint_ns": str(configurable.get("checkpoint_ns", "")),
                "created_at": str(checkpoint.get("ts", "")),
                "source": str(metadata.get("source", "")),
                "step": metadata.get("step"),
                "channel_names": sorted(str(key) for key in channels),
                "pending_write_count": len(item.pending_writes or ()),
            }
            if include_state:
                record["state"] = channels
            yield record

    async def checkpoint_count(self, thread_id: str) -> int:
        checkpointer = await self.require_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}
        count = 0
        async for _ in checkpointer.alist(config):
            count += 1
        return count

    async def purge_thread(self, thread_id: str) -> bool:
        checkpointer = await self.require_checkpointer()
        had_checkpoints = await self.checkpoint_count(thread_id) > 0
        await checkpointer.adelete_thread(thread_id)
        return had_checkpoints


__all__ = ["WorkflowCheckpointService"]
