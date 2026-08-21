from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path
import re
import tempfile
import threading

from agent_shell.storage.permissions import secure_directory, secure_file


_DIAGNOSTIC_ID = re.compile(r"^[0-9a-f]{32}$")


class RuntimeDiagnosticDetailStore:
    """Own optional local exception details for runtime diagnostics."""

    def __init__(self, directory: Path) -> None:
        self._lock = threading.Lock()
        self._directory = directory
        self.directory_permission = secure_directory(directory)

    @staticmethod
    def _validate_id(diagnostic_id: str) -> str:
        if not _DIAGNOSTIC_ID.fullmatch(diagnostic_id):
            raise ValueError("runtime diagnostic id is invalid")
        return diagnostic_id

    def _path(self, diagnostic_id: str) -> Path:
        return self._directory / f"diagnostic-{self._validate_id(diagnostic_id)}.log"

    def write(self, diagnostic_id: str, lines: Iterable[str]) -> bool:
        path = self._path(diagnostic_id)
        temporary: Path | None = None
        with self._lock:
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    newline="",
                    dir=self._directory,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    for line in lines:
                        stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
                secure_file(temporary)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return True

    def download_path(self, diagnostic_id: str) -> Path | None:
        path = self._path(diagnostic_id)
        with self._lock:
            return path if path.is_file() else None

    def retain(self, diagnostic_ids: set[str]) -> None:
        expected = {self._path(diagnostic_id) for diagnostic_id in diagnostic_ids}
        with self._lock:
            for path in self._directory.glob("diagnostic-*.log"):
                if path not in expected:
                    path.unlink(missing_ok=True)


__all__ = ["RuntimeDiagnosticDetailStore"]
