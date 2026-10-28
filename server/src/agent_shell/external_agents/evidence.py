"""Own the files for one External Agent Session without blocking its loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import BinaryIO, TextIO

from agent_shell.async_tasks import complete_before_cancel
from agent_shell.external_agents.contracts import ExternalAgentRunEvent
from agent_shell.external_agents.layout import (
    AntigravityLifecycleLayout,
    AntigravitySessionLayout,
)
from agent_shell.storage.atomic_files import write_text_atomic


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    write_text_atomic(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")


async def recorded_definition_revision(
    layout: AntigravityLifecycleLayout, conversation_id: str
) -> str | None:
    """Read the definition revision that created a recorded conversation."""

    def read() -> str | None:
        if not layout.sessions.is_dir():
            return None
        for directory in sorted(layout.sessions.iterdir()):
            meta_file = directory / "meta.json"
            if not meta_file.is_file():
                continue
            try:
                document = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(document, Mapping):
                continue
            if document.get("conversation_id") != conversation_id:
                continue
            revision = document.get("definition_revision")
            if isinstance(revision, str) and revision:
                return revision
        return None

    return await complete_before_cancel(asyncio.to_thread(read))


class SessionEvidence:
    """Sequential event writes, terminal JSON and one independently collected stderr."""

    def __init__(
        self,
        session: AntigravitySessionLayout,
        on_event: Callable[[ExternalAgentRunEvent], None] | None,
    ) -> None:
        self._session = session
        self._on_event = on_event
        self._events: TextIO | None = None

    def _open(self) -> None:
        self._session.create()
        self._events = self._session.event_log.open(mode="a", encoding="utf-8")

    def _close(self) -> None:
        if self._events is not None:
            self._events.close()
            self._events = None

    async def __aenter__(self) -> SessionEvidence:
        try:
            await complete_before_cancel(asyncio.to_thread(self._open))
        except BaseException:
            await complete_before_cancel(asyncio.to_thread(self._close))
            raise
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await complete_before_cancel(asyncio.to_thread(self._close))

    def _append(self, event: ExternalAgentRunEvent) -> None:
        assert self._events is not None
        record = json.dumps(event.as_record(), ensure_ascii=False, default=str)
        self._events.write(record + "\n")
        self._events.flush()

    async def emit(self, kind: str, payload: Mapping[str, object]) -> None:
        event = ExternalAgentRunEvent(kind, dict(payload), datetime.now(UTC).isoformat())

        async def record_and_notify() -> None:
            await asyncio.to_thread(self._append, event)
            if self._on_event is not None:
                self._on_event(event)

        # A committed event keeps its callback even if cancellation arrives
        # during the write. The callback runs on the owning event loop.
        await complete_before_cancel(record_and_notify())

    async def save_metadata(self, meta: Mapping[str, object]) -> None:
        await complete_before_cancel(
            asyncio.to_thread(_write_json, self._session.meta_file, meta)
        )

    async def save_result(
        self, meta: Mapping[str, object], result: Mapping[str, object]
    ) -> None:
        def save() -> None:
            _write_json(self._session.meta_file, meta)
            _write_json(self._session.result_file, result)

        await complete_before_cancel(asyncio.to_thread(save))

    async def collect_stderr(
        self, stream: asyncio.StreamReader, process_exited: asyncio.Event, chunk_bytes: int
    ) -> str:
        log: BinaryIO | None = None
        chunks: list[bytes] = []

        def open_log() -> None:
            nonlocal log
            log = self._session.stderr_log.open(mode="wb")

        def append(chunk: bytes) -> None:
            assert log is not None
            log.write(chunk)
            log.flush()

        stopped = asyncio.create_task(process_exited.wait())
        pending: asyncio.Task[bytes] | None = None
        try:
            await complete_before_cancel(asyncio.to_thread(open_log))
            while True:
                pending = asyncio.create_task(stream.read(chunk_bytes))
                await asyncio.wait((pending, stopped), return_when=asyncio.FIRST_COMPLETED)
                if not pending.done():
                    # The CLI exited but a descendant can keep stderr open.
                    # Drain bytes already delivered; do not wait for its EOF.
                    await asyncio.sleep(0)
                    if not pending.done():
                        break
                chunk = pending.result()
                if not chunk:
                    break
                chunks.append(chunk)
                await complete_before_cancel(asyncio.to_thread(append, chunk))
        finally:
            async def close() -> None:
                stopped.cancel()
                tasks = [stopped]
                if pending is not None:
                    pending.cancel()
                    tasks.append(pending)
                await asyncio.gather(*tasks, return_exceptions=True)
                if log is not None:
                    await asyncio.to_thread(log.close)

            await complete_before_cancel(close())
        return b"".join(chunks).decode("utf-8", errors="replace")
