from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.storage.media_outputs import MediaOutputStore, MediaProjection


@dataclass(frozen=True, slots=True)
class _HandledMedia:
    message_id: str
    block_index: int
    projection: MediaProjection


class MainAgentMediaResponse:
    """Request-local response media projection and structured metadata."""

    def __init__(self, store: MediaOutputStore, request_id: str) -> None:
        self._store = store
        self._request_id = request_id
        self._by_event_key: dict[str, _HandledMedia] = {}
        self._ordered: list[_HandledMedia] = []

    async def project(self, event: MediaContentBlock) -> str | None:
        event_key = event.stream_id or (
            f"{event.message_id}:{event.block_index}:{len(self._ordered)}"
        )
        if event_key in self._by_event_key:
            return None
        persist_task = asyncio.create_task(
            asyncio.to_thread(
                self._store.persist,
                request_id=self._request_id,
                message_id=event.message_id,
                block_index=event.block_index,
                block=dict(event.content),
            )
        )
        try:
            projection = await asyncio.shield(persist_task)
        except asyncio.CancelledError:
            try:
                await persist_task
            except Exception:
                pass
            raise
        handled = _HandledMedia(
            message_id=event.message_id,
            block_index=event.block_index,
            projection=projection,
        )
        self._by_event_key[event_key] = handled
        self._ordered.append(handled)
        return projection.notification

    @property
    def assets(self) -> list[dict[str, Any]]:
        return [
            deepcopy(item.projection.asset)
            for item in self._ordered
            if item.projection.asset is not None
        ]
