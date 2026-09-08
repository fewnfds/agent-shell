from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite import AsyncSqliteStore


_persistence_root: Path | None = None


def configure_persistence(root: Path) -> None:
    """Bind Agent Server persistence to the current instance data root."""

    global _persistence_root
    _persistence_root = root.resolve()


def _database_path(filename: str) -> Path:
    if _persistence_root is None:
        raise RuntimeError(
            "LangGraph persistence must be configured by the Agent Shell launcher"
        )
    return _persistence_root / filename


@asynccontextmanager
async def generate_checkpointer() -> AsyncIterator[AsyncSqliteSaver]:
    """Yield the official async SQLite checkpointer for Agent Server."""

    async with AsyncSqliteSaver.from_conn_string(
        str(_database_path("checkpoints.sqlite3"))
    ) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def generate_store() -> AsyncIterator[AsyncSqliteStore]:
    """Yield the official async SQLite Store for Agent Server."""

    async with AsyncSqliteStore.from_conn_string(
        str(_database_path("store.sqlite3"))
    ) as store:
        await store.setup()
        yield store


__all__ = [
    "configure_persistence",
    "generate_checkpointer",
    "generate_store",
]
