"""Cancellation handling for work that must finish before its owner closes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from contextlib import suppress


async def complete_before_cancel[T](operation: Awaitable[T]) -> T:
    """Join owned work before cancellation can close its files or release a claim."""

    task = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(task)
        # Retrieve a concurrent failure; the caller's cancellation takes priority.
        with suppress(asyncio.CancelledError, Exception):
            task.result()
        raise
