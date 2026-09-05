from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from agent_shell.file_manager import FileManagerError, FileManagerService
from agent_shell.runtime.media_events import MediaContentBlock


_MEDIA_LABELS = {
    "image": "图片",
    "audio": "音频",
    "video": "视频",
    "file": "文件",
}
_MIME_EXTENSIONS = {
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-wav": ".wav",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "video/mp4": ".mp4",
    "video/mpeg": ".mpeg",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


class MainAgentMediaResponse:
    """Project response media to persistent user files and text notifications."""

    def __init__(
        self,
        files: FileManagerService,
        request_id: str,
    ) -> None:
        self._files = files
        self._request_id = request_id
        self._handled_event_keys: set[str] = set()

    @staticmethod
    def _source_data(block: dict[str, Any]) -> tuple[str, str] | None:
        mime_type = str(block.get("mime_type") or "").strip().lower()
        encoded = block.get("base64")
        if not isinstance(encoded, str) and block.get("source_type") == "base64":
            encoded = block.get("data")
        if isinstance(encoded, str) and encoded and mime_type:
            return encoded, mime_type
        url = block.get("url")
        if isinstance(url, str) and url.startswith("data:"):
            header, separator, encoded = url.partition(",")
            if separator and header.endswith(";base64"):
                return encoded, header[5:-7].strip().lower()
        return None

    @staticmethod
    def _extension(media_type: str, mime_type: str) -> str | None:
        if "/" not in mime_type or ";" in mime_type:
            return None
        if media_type != "file" and not mime_type.startswith(f"{media_type}/"):
            return None
        return _MIME_EXTENSIONS.get(mime_type, ".bin")

    @staticmethod
    def _decode(encoded: str) -> bytes | None:
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None

    @staticmethod
    def _unsaved(label: str) -> str:
        return f"AI发送来了【{label}】，但返回内容无法保存。"

    def _persist(self, block: dict[str, Any], block_index: int) -> str:
        media_type = str(block.get("type") or "")
        label = _MEDIA_LABELS.get(media_type, "文件")
        source = self._source_data(block)
        if source is None:
            return self._unsaved(label)
        encoded, mime_type = source
        extension = self._extension(media_type, mime_type)
        content = self._decode(encoded)
        if extension is None or content is None:
            return self._unsaved(label)

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        filename = f"block-{block_index:04d}-{str(uuid4())[:8]}{extension}"
        path = (
            PurePosixPath("data/files/generated")
            / month
            / self._request_id
            / filename
        ).as_posix()
        try:
            saved = self._files.save_generated_file(path, content)
        except FileManagerError:
            return self._unsaved(label)
        return f"AI发送来了【{label}】，已保存到【{saved['path']}】。"

    async def project(self, event: MediaContentBlock) -> str | None:
        event_key = event.stream_id or f"{event.message_id}:{event.block_index}"
        if event_key in self._handled_event_keys:
            return None
        persist_task = asyncio.create_task(
            asyncio.to_thread(self._persist, dict(event.content), event.block_index)
        )
        try:
            notification = await asyncio.shield(persist_task)
        except asyncio.CancelledError:
            try:
                await persist_task
            except Exception:
                pass
            raise
        self._handled_event_keys.add(event_key)
        return notification
