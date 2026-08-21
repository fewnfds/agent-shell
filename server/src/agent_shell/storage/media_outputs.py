from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any
from uuid import uuid4

from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.permissions import secure_directory, secure_file
from agent_shell.storage.runtime_policy import RUNTIME_POLICY_DEFAULTS, RuntimePolicyStore


_LOGGER = logging.getLogger(__name__)
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


@dataclass(frozen=True, slots=True)
class MediaProjection:
    notification: str
    structured_block: dict[str, Any]
    asset: dict[str, Any] | None


class MediaOutputStore:
    """Persist private response media and clean up finalized request assets."""

    def __init__(
        self,
        database: SQLiteDatabase,
        root: Path,
        runtime_policy: RuntimePolicyStore | None = None,
    ) -> None:
        self._database = database
        self._runtime_policy = runtime_policy
        self.root = root.resolve()
        self.directory_permission = secure_directory(self.root)
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE media_output_assets SET finalized = 1 WHERE finalized = 0"
            )
            connection.commit()
        self.cleanup_unreferenced()

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

    def _decode(self, encoded: str) -> bytes | None:
        maximum_bytes = (
            self._runtime_policy.snapshot().media_output_bytes
            if self._runtime_policy is not None
            else RUNTIME_POLICY_DEFAULTS.media_output_bytes
        )
        maximum_encoded = ((maximum_bytes + 2) // 3) * 4
        if len(encoded) > maximum_encoded:
            return None
        try:
            value = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return None
        return value if len(value) <= maximum_bytes else None

    @staticmethod
    def _safe_filename(value: object) -> str:
        if not isinstance(value, str):
            return ""
        name = Path(value).name.strip()
        if not name or name in {".", ".."}:
            return ""
        return name[:255]

    def persist(
        self,
        *,
        request_id: str,
        message_id: str,
        block_index: int,
        block: dict[str, Any],
    ) -> MediaProjection:
        media_type = str(block.get("type") or "")
        label = _MEDIA_LABELS.get(media_type, "文件")
        source = self._source_data(block)
        if source is None:
            return self._unsaved(block, label, reason="source_unavailable")
        encoded, mime_type = source
        extension = self._extension(media_type, mime_type)
        data = self._decode(encoded)
        if extension is None or data is None:
            return self._unsaved(block, label, reason="content_invalid")

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        directory = (self.root / month / request_id).resolve()
        try:
            directory.relative_to(self.root)
        except ValueError:
            return self._unsaved(block, label, reason="path_invalid")
        asset_id = str(uuid4())
        filename = f"block-{block_index:04d}-{asset_id[:8]}{extension}"
        destination = directory / filename
        temporary = directory / f".{filename}.tmp"
        relative_directory = PurePosixPath("data/media/outputs") / month / request_id
        relative_path = relative_directory / filename
        try:
            secure_directory(directory)
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            secure_file(destination)
            asset = {
                "id": asset_id,
                "type": media_type,
                "mime_type": mime_type,
                "relative_path": relative_path.as_posix(),
                "relative_directory": relative_directory.as_posix(),
                "byte_size": len(data),
                "filename": self._safe_filename(block.get("filename")),
            }
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO media_output_assets "
                    "(id, request_id, message_id, block_index, created_at, media_type, "
                    "mime_type, relative_path, byte_size, original_filename, finalized) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        asset_id,
                        request_id,
                        message_id,
                        block_index,
                        now.isoformat(timespec="milliseconds"),
                        media_type,
                        mime_type,
                        asset["relative_path"],
                        len(data),
                        asset["filename"],
                    ),
                )
                connection.commit()
        except (OSError, sqlite3.Error, ValueError):
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            return self._unsaved(block, label, reason="persistence_failed")

        return MediaProjection(
            notification=(
                f"AI发送来了【{label}】，已保存到【{asset['relative_directory']}】。"
            ),
            structured_block={
                "type": media_type,
                "asset_id": asset_id,
                "mime_type": mime_type,
                "relative_path": asset["relative_path"],
                "byte_size": len(data),
            },
            asset=asset,
        )

    @staticmethod
    def _unsaved(
        block: dict[str, Any], label: str, *, reason: str
    ) -> MediaProjection:
        media_type = str(block.get("type") or "file")
        source_type = next(
            (
                key
                for key in ("base64", "url", "file_id")
                if key in block
            ),
            str(block.get("source_type") or "unknown"),
        )
        structured = {
            "type": media_type,
            "saved": False,
            "reason": reason,
            "source_type": source_type,
        }
        mime_type = block.get("mime_type")
        if isinstance(mime_type, str):
            structured["mime_type"] = mime_type
        return MediaProjection(
            notification=f"AI发送来了【{label}】，但返回内容无法保存。",
            structured_block=structured,
            asset=None,
        )

    def finish_request(self, request_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE media_output_assets SET finalized = 1 WHERE request_id = ?",
                (request_id,),
            )
            connection.commit()
        self.cleanup_unreferenced()

    def cleanup_unreferenced(self) -> None:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT id, relative_path FROM media_output_assets "
                "WHERE finalized = 1"
            ).fetchall()
        deleted_ids = []
        for row in rows:
            if self._delete_relative_path(str(row["relative_path"])):
                deleted_ids.append(str(row["id"]))
            else:
                _LOGGER.warning(
                    "Unable to remove media output asset %s; cleanup will retry.",
                    row["id"],
                )
        if deleted_ids:
            with self._database.transaction() as connection:
                connection.executemany(
                    "DELETE FROM media_output_assets WHERE id = ?",
                    ((asset_id,) for asset_id in deleted_ids),
                )
                connection.commit()

    def _delete_relative_path(self, relative_path: str) -> bool:
        parts = PurePosixPath(relative_path).parts
        prefix = ("data", "media", "outputs")
        if parts[:3] != prefix:
            return False
        target = (self.root.joinpath(*parts[3:])).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            return False
        try:
            target.unlink(missing_ok=True)
        except OSError:
            return False
        parent = target.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True
