from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class DetachedTaskManager:
    """Own response and stream-consumer continuations during app lifetime."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._started = False

    def create(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> asyncio.Task[None]:
        if not self._started:
            raise RuntimeError("the detached task manager is not started")
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task


__all__ = ["DetachedTaskManager"]
