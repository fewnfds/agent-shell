from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
from typing import Mapping, Any

from agent_shell.redaction import redact_for_boundary
from agent_shell.request_context import current_actor, current_request_id
from agent_shell.storage.permissions import PermissionStatus, secure_directory, secure_file


SECURITY_EVENT_NAMES = frozenset(
    {
        "service_started",
        "service_stopped",
        "security_configuration_loaded",
        "configuration_updated",
        "configuration_deleted",
        "provider_secret_rotated",
        "provider_secret_cleared",
        "management_request_failed",
        "authentication_failed",
    }
)

SECURITY_EVENT_FIELDS = {
    "service_started": frozenset({"deployment_mode"}),
    "service_stopped": frozenset({"reason"}),
    "security_configuration_loaded": frozenset(
        {"deployment_mode", "management_scope", "api_scope", "trusted_proxy"}
    ),
    "configuration_updated": frozenset(
        {"action", "entity", "entity_id", "capability_type", "state"}
    ),
    "configuration_deleted": frozenset(
        {"action", "entity", "entity_id", "capability_type"}
    ),
    "provider_secret_rotated": frozenset({"block_id"}),
    "provider_secret_cleared": frozenset({"block_id", "reason"}),
    "management_request_failed": frozenset(
        {"method", "path", "status_code", "code", "issue_count"}
    ),
    "authentication_failed": frozenset(
        {"required_scope", "status_code", "code"}
    ),
}

SYSTEM_EVENT_CATEGORIES = {
    "service_started": "lifecycle",
    "service_stopped": "lifecycle",
    "security_configuration_loaded": "security",
    "configuration_updated": "configuration",
    "configuration_deleted": "configuration",
    "provider_secret_rotated": "security",
    "provider_secret_cleared": "security",
    "management_request_failed": "error",
    "authentication_failed": "security",
}

SYSTEM_EVENT_LEVELS = {
    "management_request_failed": "error",
    "authentication_failed": "warning",
}


SecurityEventFailureReporter = Callable[[BaseException, str], None]
SystemEventPublisher = Callable[[dict[str, object]], None]


class _ReportingRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        filename: Path,
        *,
        max_bytes: int,
        report_failure: SecurityEventFailureReporter,
    ) -> None:
        self._report_failure = report_failure
        super().__init__(
            filename,
            maxBytes=max_bytes,
            backupCount=0,
            encoding="utf-8",
            delay=True,
        )

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        with open(self.baseFilename, "w", encoding=self.encoding):
            pass

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exc_info()[1]
        if error is None:
            error = OSError("security event persistence failed")
        self._report_failure(
            error,
            str(getattr(record, "security_event_request_id", "")),
        )


class SecurityEventLogger:
    """Bounded metadata events; configuration and request bodies are never accepted."""

    def __init__(self, logs_dir: Path, *, max_bytes: int = 5 * 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("system event maximum size must be positive")
        self._lock = threading.Lock()
        self._max_bytes = max_bytes
        self._failure_reporter: SecurityEventFailureReporter | None = None
        self._publisher: SystemEventPublisher | None = None
        self.directory_permission = secure_directory(logs_dir)
        self.path = logs_dir / "security-events.jsonl"
        self.path.touch(exist_ok=True)
        self.file_permission = secure_file(self.path)
        for suffix in (".1", ".2"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        self._enforce_current_limit()

    @property
    def permission_statuses(self) -> tuple[PermissionStatus, PermissionStatus]:
        return self.directory_permission, self.file_permission

    def set_failure_reporter(
        self, reporter: SecurityEventFailureReporter
    ) -> None:
        self._failure_reporter = reporter

    def set_publisher(self, publisher: SystemEventPublisher) -> None:
        self._publisher = publisher

    def _enforce_current_limit(self) -> None:
        if self.path.stat().st_size > self._max_bytes:
            self.path.write_text("", encoding="utf-8")

    def set_max_bytes(self, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("system event maximum size must be positive")
        with self._lock:
            self._max_bytes = max_bytes
            self._enforce_current_limit()

    @staticmethod
    def _public_record(record: Mapping[str, Any]) -> dict[str, object]:
        event = str(record.get("event", ""))
        metadata = record.get("metadata", {})
        public = {
            "timestamp": str(record.get("timestamp", "")),
            "event": event,
            "category": SYSTEM_EVENT_CATEGORIES.get(event, "system"),
            "level": SYSTEM_EVENT_LEVELS.get(event, "info"),
            "request_id": str(record.get("request_id", "")),
            "actor": str(record.get("actor", "")),
            "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
        }
        safe = redact_for_boundary("event-log", public)
        return safe if isinstance(safe, dict) else {
            "timestamp": "",
            "event": event,
            "category": SYSTEM_EVENT_CATEGORIES.get(event, "system"),
            "level": SYSTEM_EVENT_LEVELS.get(event, "info"),
            "request_id": "",
            "actor": "",
            "metadata": {"status": "[UNAVAILABLE]"},
        }

    def public_records(self) -> list[dict[str, object]]:
        """Return persisted records in storage order with the public boundary applied."""
        records: list[dict[str, object]] = []
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if (
                    not isinstance(record, dict)
                    or record.get("event") not in SECURITY_EVENT_NAMES
                ):
                    continue
                records.append(self._public_record(record))
        return records

    def delete_public_records(
        self,
        predicate: Callable[[dict[str, object]], bool],
    ) -> int:
        deleted = 0
        retained: list[str] = []
        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except (TypeError, ValueError):
                    retained.append(line)
                    continue
                if (
                    isinstance(record, dict)
                    and record.get("event") in SECURITY_EVENT_NAMES
                    and predicate(self._public_record(record))
                ):
                    deleted += 1
                else:
                    retained.append(line)
            content = "".join(f"{line}\n" for line in retained)
            self.path.write_text(content, encoding="utf-8")
        return deleted

    def _report_write_failure(self, error: BaseException, request_id: str) -> None:
        reporter = self._failure_reporter
        if reporter is not None:
            try:
                reporter(error, request_id)
                return
            except Exception:
                pass
        try:
            logging.getLogger(__name__).error(
                "security_event_record_failed request_id=%s", request_id or "-"
            )
        except Exception:
            pass

    def emit(
        self,
        event: str,
        metadata: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
        actor: str | None = None,
    ) -> None:
        if event not in SECURITY_EVENT_NAMES:
            raise ValueError(f"unsupported security event: {event}")
        raw_metadata = dict(metadata or {})
        unknown = set(raw_metadata) - SECURITY_EVENT_FIELDS[event]
        if unknown:
            raise ValueError(f"unsupported metadata fields for security event: {event}")
        safe_metadata = redact_for_boundary("event-log", raw_metadata)
        if not isinstance(safe_metadata, dict):
            safe_metadata = {"status": "[UNAVAILABLE]"}
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "request_id": request_id if request_id is not None else current_request_id(),
            "actor": actor if actor is not None else current_actor(),
            "metadata": safe_metadata,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            handler = _ReportingRotatingFileHandler(
                self.path,
                max_bytes=self._max_bytes,
                report_failure=self._report_write_failure,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            log_record = logging.LogRecord(
                name=__name__,
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=line,
                args=(),
                exc_info=None,
            )
            log_record.security_event_request_id = record["request_id"]
            try:
                handler.handle(log_record)
            finally:
                try:
                    handler.close()
                except Exception as exc:
                    self._report_write_failure(exc, str(record["request_id"] or ""))
        publisher = self._publisher
        if publisher is not None:
            try:
                publisher(
                    {"type": "system_log", "entry": self._public_record(record)}
                )
            except Exception:
                pass


def emit_configuration_events(
    logger: SecurityEventLogger | None,
    *,
    action: str,
    entity: str,
    entity_id: str,
    capability_type: str = "",
    state: str = "",
) -> None:
    if logger is None:
        return
    metadata = {
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "capability_type": capability_type,
    }
    if state:
        metadata["state"] = state
    logger.emit(
        "configuration_deleted" if action == "deleted" else "configuration_updated",
        metadata,
    )
