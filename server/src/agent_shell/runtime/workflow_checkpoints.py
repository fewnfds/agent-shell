from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent_shell.runtime.limits import GRAPH_RECURSION_LIMIT
from agent_shell.storage.database import SQLiteFile


@dataclass(slots=True)
class WorkflowCheckpointContext:
    """One Workflow invocation configuration for the official Checkpointer."""

    thread_id: str
    run_id: UUID
    request_id: str
    workflow_id: str
    workflow_name: str
    messages_sha: str

    def config(self) -> dict[str, object]:
        return {
            "recursion_limit": GRAPH_RECURSION_LIMIT,
            "configurable": {"thread_id": self.thread_id},
            "run_id": self.run_id,
            "run_name": f"workflow:{self.workflow_name}",
            "tags": ["agent-shell", "workflow"],
            "metadata": {
                "thread_id": self.thread_id,
                "request_id": self.request_id,
                "workflow_id": self.workflow_id,
                "workflow_name": self.workflow_name,
                "messages_sha": self.messages_sha,
            },
        }

class WorkflowCheckpointService:
    """Own official Workflow checkpoints; Run history has a separate owner."""

    def __init__(
        self,
        database: SQLiteFile,
        *,
        tracing_enabled: bool,
        langsmith_project: str,
    ) -> None:
        self._database_path = database.path
        self.tracing_enabled = tracing_enabled
        self.langsmith_project = langsmith_project
        self._context: AbstractAsyncContextManager[AsyncSqliteSaver] | None = None
        self._checkpointer: AsyncSqliteSaver | None = None

    @property
    def checkpointer(self) -> AsyncSqliteSaver:
        if self._checkpointer is None:
            raise RuntimeError("the Workflow checkpointer is not started")
        return self._checkpointer

    async def start(self) -> None:
        context = AsyncSqliteSaver.from_conn_string(str(self._database_path))
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

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
        self._context = None
        self._checkpointer = None

    def create_context(
        self,
        *,
        request_id: str,
        workflow_id: str,
        workflow_name: str,
        messages_sha: str,
        run_id: UUID | None = None,
        thread_id: str | None = None,
    ) -> WorkflowCheckpointContext:
        return WorkflowCheckpointContext(
            thread_id=thread_id or str(uuid4()),
            run_id=run_id or uuid4(),
            request_id=request_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            messages_sha=messages_sha,
        )

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

    async def iter_checkpoint_history(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        include_state: bool = False,
    ) -> AsyncIterator[dict[str, object]]:
        config = {"configurable": {"thread_id": thread_id}}
        async for item in self.checkpointer.alist(config, limit=limit):
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
        config = {"configurable": {"thread_id": thread_id}}
        count = 0
        async for _ in self.checkpointer.alist(config):
            count += 1
        return count

    async def purge_thread(self, thread_id: str) -> bool:
        had_checkpoints = await self.checkpoint_count(thread_id) > 0
        await self.checkpointer.adelete_thread(thread_id)
        return had_checkpoints


__all__ = ["WorkflowCheckpointContext", "WorkflowCheckpointService"]
