from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import threading
from typing import Any

from agent_shell.storage.permissions import secure_directory, secure_file


_SCOPE_LABEL = re.compile(r"[^A-Za-z0-9._-]")
_BINARY_KEYS = frozenset(
    {"base64", "data", "image_base64", "audio_base64", "file_base64"}
)
_DATA_URI_PREFIX = "data:"


def _placeholder(value: str) -> str:
    return f"<omitted {len(value)} chars>"


def project_archive_value(value: Any) -> Any:
    """Keep text, replace inline binary with a size placeholder.

    Model calls may carry base64 images, audio or files. Those dominate archive
    size and stay recoverable from the original source, so the archive records
    their presence and size instead of the payload itself.
    """

    if isinstance(value, Mapping):
        return {
            str(key): (
                _placeholder(item)
                if isinstance(item, str)
                and item
                and (
                    str(key).lower() in _BINARY_KEYS
                    or item.startswith(_DATA_URI_PREFIX)
                )
                else project_archive_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [project_archive_value(item) for item in value]
    if isinstance(value, str) and value.startswith(_DATA_URI_PREFIX):
        return _placeholder(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class ModelCallArchive:
    """Own the per-scope record of real model requests and responses.

    The archive is a local diagnostic carrier: one JSONL file per Lifecycle,
    written after each provider attempt. It never participates in scheduling or
    response projection, so a write failure is reported as a diagnostic instead
    of changing the model call.
    """

    def __init__(
        self,
        directory: Path,
        *,
        redact_secret_text: Callable[[str], str] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._directory = directory
        self._redact_secret_text = redact_secret_text or (lambda value: value)
        self.directory_permission = secure_directory(directory)

    def _path(self, scope_id: str) -> Path:
        safe = _SCOPE_LABEL.sub("_", scope_id) or "unscoped"
        return self._directory / f"model-calls-{safe}.jsonl"

    def append(self, scope_id: str, record: Mapping[str, Any]) -> None:
        projected = project_archive_value(dict(record))
        line = (
            json.dumps(projected, ensure_ascii=False, default=str, separators=(",", ":"))
            + "\n"
        )
        line = self._redact_secret_text(line)
        path = self._path(scope_id)
        with self._lock:
            if not path.exists():
                path.touch()
                permission = secure_file(path)
                if not permission.enforced:
                    path.unlink(missing_ok=True)
                    raise PermissionError(
                        "The model call archive file is not private."
                    )
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())

    def content(self, scope_id: str) -> bytes | None:
        path = self._path(scope_id)
        with self._lock:
            if not path.is_file():
                return None
            return path.read_bytes()

    def run_request_counts(self, scope_id: str) -> dict[str, int]:
        """Count archived model-call attempts by their official Run identity."""

        path = self._path(scope_id)
        counts: dict[str, int] = {}
        with self._lock:
            if not path.is_file():
                return counts
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, Mapping):
                        continue
                    run_id = record.get("run_id")
                    if not isinstance(run_id, str) or not run_id:
                        continue
                    counts[run_id] = counts.get(run_id, 0) + 1
        return counts

    def discard(self, scope_id: str) -> None:
        path = self._path(scope_id)
        with self._lock:
            path.unlink(missing_ok=True)


__all__ = ["ModelCallArchive", "project_archive_value"]
