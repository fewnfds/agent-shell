from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Callable
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from agent_shell.storage.atomic_files import write_private_text_atomic
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.environment import CredentialByteProjector
from agent_shell.storage.history_retention import HistoryRetentionStore
from agent_shell.storage.permissions import secure_directory, secure_file


_ID = re.compile(r"^[0-9a-f]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(slots=True)
class ProviderHttpCapture:
    id: str
    metadata: dict[str, object]
    request_projector: CredentialByteProjector
    response_projector: CredentialByteProjector
    observed_request_bytes: int = 0
    observed_response_bytes: int = 0
    stored_request_bytes: int = 0
    stored_response_bytes: int = 0
    capture_error: str = ""
    finished: bool = False


class ProviderHttpLogStore:
    """Own Provider HTTP summaries, body files, retention, and ZIP snapshots."""

    def __init__(
        self,
        database: SQLiteDatabase,
        root: Path,
        retention: HistoryRetentionStore,
        *,
        notify_change: Callable[[], None] | None = None,
    ) -> None:
        self._database = database
        self._root = root.resolve()
        self._downloads = self._root / "downloads"
        self._retention = retention
        self._notify_change = notify_change or (lambda: None)
        self._lock = threading.RLock()
        secure_directory(self._root)
        secure_directory(self._downloads)
        self.recover()

    def _changed(self) -> None:
        try:
            self._notify_change()
        except Exception:
            # A management refresh signal must not change Provider execution.
            pass

    @staticmethod
    def _project(value: str, secrets: tuple[bytes, ...]) -> str:
        raw = value.encode("utf-8", errors="surrogateescape")
        for secret in secrets:
            raw = raw.replace(secret, b"[REDACTED]")
        return raw.decode("utf-8", errors="replace")

    def _entry_dir(self, item_id: str) -> Path:
        if _ID.fullmatch(item_id) is None:
            raise ValueError("invalid Provider HTTP log id")
        return self._root / item_id

    @staticmethod
    def _summary(method: str, url: str, status: int | None, state: str) -> str:
        result = f"HTTP {status}" if status is not None else "no HTTP response"
        return f"{method} {url} · {result} · {state}"

    def _write_metadata(self, capture: ProviderHttpCapture) -> None:
        path = self._entry_dir(capture.id) / "metadata.json"
        write_private_text_atomic(
            path,
            json.dumps(capture.metadata, ensure_ascii=False, indent=2) + "\n",
        )

    def begin(
        self,
        *,
        method: str,
        url: str,
        headers: list[tuple[str, str]],
        secrets: tuple[bytes, ...],
        request_id: str,
        context: dict[str, str] | None = None,
    ) -> ProviderHttpCapture:
        item_id = uuid4().hex
        occurred_at = _now()
        projected_url = self._project(url, secrets)
        projected_headers = [
            [self._project(name, secrets), self._project(value, secrets)]
            for name, value in headers
        ]
        metadata: dict[str, object] = {
            "id": item_id,
            "occurred_at": occurred_at,
            "ended_at": None,
            "request": {
                "method": method,
                "url": projected_url,
                "headers": projected_headers,
                "body_file": "request.body",
                "representation": "HTTP entity body after credential projection",
            },
            "response": None,
            "request_id": request_id,
            "context": {
                key: self._project(value, secrets) for key, value in (context or {}).items()
            },
            "state": "active",
            "capture_complete": False,
        }
        capture = ProviderHttpCapture(
            id=item_id,
            metadata=metadata,
            request_projector=CredentialByteProjector(secrets),
            response_projector=CredentialByteProjector(secrets),
        )
        with self._lock:
            entry = self._entry_dir(item_id)
            try:
                secure_directory(entry)
                request_body = entry / "request.body"
                request_body.touch()
                secure_file(request_body)
                self._write_metadata(capture)
                with self._database.transaction() as connection:
                    connection.execute(
                        """INSERT INTO provider_http_logs
                        (id, occurred_at, ended_at, level, state, summary,
                         request_id, context_json, method, url, status_code)
                        VALUES (?, ?, NULL, 'info', 'active', ?, ?, ?, ?, ?, NULL)""",
                        (
                            item_id,
                            occurred_at,
                            self._summary(method, projected_url, None, "active"),
                            request_id,
                            json.dumps(metadata["context"], ensure_ascii=False),
                            method,
                            projected_url,
                        ),
                    )
            except BaseException:
                if entry.exists():
                    shutil.rmtree(entry)
                raise
        self._changed()
        return capture

    def _append(self, capture: ProviderHttpCapture, name: str, content: bytes) -> None:
        if not content:
            return
        path = self._entry_dir(capture.id) / name
        with self._lock:
            if capture.finished:
                return
            newly_created = not path.exists()
            with path.open("ab") as stream:
                if newly_created:
                    secure_file(path)
                stream.write(content)

    def append_request(self, capture: ProviderHttpCapture, chunk: bytes) -> None:
        with self._lock:
            if capture.finished:
                return
            capture.observed_request_bytes += len(chunk)
            content = capture.request_projector.write(chunk)
            self._append(capture, "request.body", content)
            capture.stored_request_bytes += len(content)

    def append_response(self, capture: ProviderHttpCapture, chunk: bytes) -> None:
        with self._lock:
            if capture.finished:
                return
            capture.observed_response_bytes += len(chunk)
            content = capture.response_projector.write(chunk)
            self._append(capture, "response.body", content)
            capture.stored_response_bytes += len(content)

    def response_headers(
        self,
        capture: ProviderHttpCapture,
        *,
        status: int,
        http_version: str,
        headers: list[tuple[str, str]],
        representation: str,
        secrets: tuple[bytes, ...],
    ) -> None:
        response = {
            "status": status,
            "http_version": http_version,
            "headers": [
                [self._project(name, secrets), self._project(value, secrets)]
                for name, value in headers
            ],
            "body_file": "response.body",
            "representation": representation,
        }
        with self._lock:
            capture.metadata["response"] = response
            response_body = self._entry_dir(capture.id) / "response.body"
            response_body.touch(exist_ok=True)
            secure_file(response_body)
            self._write_metadata(capture)
            with self._database.transaction() as connection:
                connection.execute(
                    """UPDATE provider_http_logs SET status_code = ?, summary = ?
                    WHERE id = ?""",
                    (
                        status,
                        self._summary(
                            str(capture.metadata["request"]["method"]),
                            str(capture.metadata["request"]["url"]),
                            status,
                            "active",
                        ),
                        capture.id,
                    ),
                )

    def finish(
        self,
        capture: ProviderHttpCapture,
        state: str,
        *,
        error: str = "",
    ) -> None:
        with self._lock:
            if capture.finished:
                return
            capture.finished = True
            for name, projector in (
                ("request.body", capture.request_projector),
                ("response.body", capture.response_projector),
            ):
                content = projector.finish()
                if content:
                    path = self._entry_dir(capture.id) / name
                    with path.open("ab") as stream:
                        secure_file(path)
                        stream.write(content)
                    if name == "request.body":
                        capture.stored_request_bytes += len(content)
                    else:
                        capture.stored_response_bytes += len(content)
            capture.metadata.update(
                ended_at=_now(),
                state=state,
                capture_complete=state == "eof" and not capture.capture_error,
                capture_error=capture.capture_error or None,
                transport_error=error or None,
                observed_request_bytes=capture.observed_request_bytes,
                observed_response_bytes=capture.observed_response_bytes,
                stored_request_bytes=capture.stored_request_bytes,
                stored_response_bytes=capture.stored_response_bytes,
            )
            self._write_metadata(capture)
            request = capture.metadata["request"]
            response = capture.metadata["response"]
            status = response["status"] if isinstance(response, dict) else None
            level = (
                "warning" if state in {"cancelled", "interrupted"}
                else "error" if error or (isinstance(status, int) and status >= 400)
                else "warning" if capture.capture_error
                else "info"
            )
            with self._database.transaction() as connection:
                connection.execute(
                    """UPDATE provider_http_logs SET ended_at = ?, state = ?,
                    level = ?, summary = ? WHERE id = ?""",
                    (
                        capture.metadata["ended_at"],
                        state,
                        level,
                        self._summary(str(request["method"]), str(request["url"]), status, state),
                        capture.id,
                    ),
                )
            self._trim_locked()
        self._changed()

    def records(self) -> list[dict[str, object]]:
        with self._lock, self._database.transaction() as connection:
            rows = connection.execute(
                """SELECT id, occurred_at, ended_at, level, state, summary,
                request_id, context_json, method, url, status_code FROM provider_http_logs"""
            ).fetchall()
            return [dict(row) for row in rows]

    def record(self, item_id: str) -> dict[str, object] | None:
        if _ID.fullmatch(item_id) is None:
            return None
        with self._lock, self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM provider_http_logs WHERE id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def _delete_locked(self, ids: list[str]) -> None:
        if not ids:
            return
        with self._database.transaction() as connection:
            connection.executemany(
                "DELETE FROM provider_http_logs WHERE id = ?", [(item_id,) for item_id in ids]
            )
        for item_id in ids:
            entry = self._entry_dir(item_id)
            if entry.exists():
                shutil.rmtree(entry)

    def _trim_locked(self) -> None:
        limit = self._retention.get_limit("provider_http")
        with self._database.transaction() as connection:
            rows = connection.execute(
                """SELECT id FROM provider_http_logs WHERE ended_at IS NOT NULL
                ORDER BY ended_at DESC, sequence DESC LIMIT -1 OFFSET ?""",
                (limit,),
            ).fetchall()
        self._delete_locked([str(row["id"]) for row in rows])

    def set_retention(self, limit: int) -> dict[str, int]:
        with self._lock:
            self._retention.set_limit("provider_http", limit)
            self._trim_locked()
        self._changed()
        return {"retention_limit": limit}

    def retention_settings(self) -> dict[str, int]:
        return {"retention_limit": self._retention.get_limit("provider_http")}

    def delete_matching(self, matches: Callable[[dict[str, object]], bool]) -> dict[str, int]:
        with self._lock:
            rows = self.records()
            selected = [row for row in rows if matches(row)]
            active = [row for row in selected if row["ended_at"] is None]
            ids = [str(row["id"]) for row in selected if row["ended_at"] is not None]
            self._delete_locked(ids)
        if ids:
            self._changed()
        return {"deleted": len(ids), "skipped_active": len(active)}

    def prepare_download(self, item_id: str) -> tuple[Path, str] | None:
        if _ID.fullmatch(item_id) is None:
            return None
        with self._lock:
            record = self.record(item_id)
            if record is None:
                return None
            if record["ended_at"] is None:
                raise RuntimeError("Provider HTTP exchange is still active")
            entry = self._entry_dir(item_id)
            descriptor, raw_path = tempfile.mkstemp(prefix="provider-http-", suffix=".zip", dir=self._downloads)
            import os
            os.close(descriptor)
            archive = Path(raw_path)
            try:
                secure_file(archive)
                with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
                    for name in ("metadata.json", "request.body", "response.body", "transport-error.txt"):
                        source = entry / name
                        if source.is_file():
                            bundle.write(source, arcname=name)
                    metadata = json.loads((entry / "metadata.json").read_text(encoding="utf-8"))
                    error = metadata.get("transport_error")
                    if error:
                        bundle.writestr("transport-error.txt", str(error) + "\n")
            except BaseException:
                archive.unlink(missing_ok=True)
                raise
            occurred_at = datetime.fromisoformat(str(record["occurred_at"]))
            stamp = occurred_at.strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
            return archive, f"agent-shell-provider-http-{stamp}-{item_id[:8]}.zip"

    def release_download(self, archive: Path) -> None:
        path = archive.resolve()
        if path.parent != self._downloads or not path.name.startswith("provider-http-") or path.suffix != ".zip":
            raise ValueError("download file is outside Provider HTTP owner")
        path.unlink(missing_ok=True)

    def recover(self) -> None:
        with self._lock:
            for archive in self._downloads.glob("provider-http-*.zip"):
                self.release_download(archive)
            interrupted_at = _now()
            with self._database.transaction() as connection:
                rows = connection.execute(
                    "SELECT id, method, url, status_code FROM provider_http_logs WHERE ended_at IS NULL"
                ).fetchall()
                known_ids = {
                    str(row["id"])
                    for row in connection.execute("SELECT id FROM provider_http_logs").fetchall()
                }
                for row in rows:
                    connection.execute(
                        """UPDATE provider_http_logs SET ended_at = ?, state = 'interrupted',
                        level = 'warning', summary = ? WHERE id = ?""",
                        (
                            interrupted_at,
                            self._summary(row["method"], row["url"], row["status_code"], "interrupted"),
                            row["id"],
                        ),
                    )
            for row in rows:
                path = self._entry_dir(str(row["id"])) / "metadata.json"
                if path.is_file():
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    metadata.update(ended_at=interrupted_at, state="interrupted", capture_complete=False)
                    write_private_text_atomic(path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
            for entry in self._root.iterdir():
                if entry.is_dir() and _ID.fullmatch(entry.name) and entry.name not in known_ids:
                    shutil.rmtree(entry)
            self._trim_locked()
