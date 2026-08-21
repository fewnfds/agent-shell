from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal

from agent_shell.runtime.diagnostics import RuntimeDiagnostics
from agent_shell.security_events import SecurityEventLogger
from agent_shell.storage.system_log_settings import MIB_BYTES, SystemLogSettingsStore


EVENT_DOWNLOAD_THRESHOLD_BYTES = 4 * 1024
EVENT_SUMMARY_MAX_CHARS = 240
EventSource = Literal["system", "runtime"]
EventLevel = Literal["debug", "info", "warning", "error"]

_SOURCE_RANK: dict[str, int] = {
    "system": 2,
    "runtime": 1,
}


def _json_text(value: object, *, pretty: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        **({"indent": 2} if pretty else {"separators": (",", ":")}),
    )


def _public_id(value: object) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _summary(*values: object) -> str:
    text = " · ".join(str(value) for value in values if value not in (None, ""))
    return text if len(text) <= EVENT_SUMMARY_MAX_CHARS else text[:239] + "…"


def _detail_json(source: EventSource, entry: dict[str, object]) -> str:
    return _json_text({"source": source, "entry": entry}, pretty=True)


class EventFeedService:
    """Merge the small set of supported management observation sources."""

    def __init__(
        self,
        system_events: SecurityEventLogger,
        diagnostics: RuntimeDiagnostics,
        system_log_settings: SystemLogSettingsStore,
    ) -> None:
        self._system_events = system_events
        self._diagnostics = diagnostics
        self._system_log_settings = system_log_settings

    def system_log_settings(self) -> dict[str, int]:
        return self._system_log_settings.snapshot()

    def set_system_log_max_size_mib(self, max_size_mib: int) -> dict[str, int]:
        settings = self._system_log_settings.set_max_size_mib(max_size_mib)
        self._system_events.set_max_bytes(max_size_mib * MIB_BYTES)
        self._system_events.emit(
            "configuration_updated",
            {
                "action": "updated",
                "entity": "system_log_settings",
                "entity_id": "system",
                "state": f"max_size_mib={max_size_mib}",
            },
        )
        return settings

    @staticmethod
    def _timestamp(value: object) -> datetime:
        timestamp = datetime.fromisoformat(str(value))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("event timestamp must include a timezone")
        return timestamp.astimezone(timezone.utc)

    @classmethod
    def _key(cls, item: dict[str, object]) -> tuple[datetime, int, str]:
        source = str(item["source"])
        return (
            cls._timestamp(item["occurred_at"]),
            _SOURCE_RANK[source],
            str(item["id"]),
        )

    @staticmethod
    def _system_item(record: dict[str, object]) -> dict[str, object]:
        item_id = _public_id(record)
        content = _detail_json("system", record)
        size = len(content.encode("utf-8"))
        return {
            "id": item_id,
            "source": "system",
            "occurred_at": record["timestamp"],
            "level": record["level"],
            "request_id": record["request_id"],
            "summary": _summary(record["event"]),
            "inline_content": content if size <= EVENT_DOWNLOAD_THRESHOLD_BYTES else None,
            "matched_in_content": False,
            "download_kind": "entry" if size > EVENT_DOWNLOAD_THRESHOLD_BYTES else None,
        }

    def _runtime_item(self, record: dict[str, object]) -> dict[str, object]:
        item_id = str(record["diagnostic_id"])
        content = _detail_json("runtime", record)
        size = len(content.encode("utf-8"))
        detail_available = self._diagnostics.detail_path(item_id) is not None
        return {
            "id": item_id,
            "source": "runtime",
            "occurred_at": record["occurred_at"],
            "level": record["severity"],
            "request_id": record.get("request_id", ""),
            "summary": _summary(
                record.get("subject_name", ""),
                record.get("summary", "") or record.get("code", ""),
            ),
            "inline_content": content if size <= EVENT_DOWNLOAD_THRESHOLD_BYTES else None,
            "matched_in_content": False,
            "download_kind": (
                "diagnostic_detail"
                if detail_available
                else "entry" if size > EVENT_DOWNLOAD_THRESHOLD_BYTES else None
            ),
        }

    @classmethod
    def _public_items(
        cls,
        records: list[dict[str, object]],
        *,
        make_item: Callable[[dict[str, object]], dict[str, object]],
        levels: set[EventLevel],
        needle: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        for record in records:
            item = make_item(record)
            timestamp = cls._timestamp(item["occurred_at"])
            if timestamp < started_at or timestamp > ended_at:
                continue
            if levels and item.get("level") not in levels:
                continue
            if needle and needle not in _json_text(record).casefold():
                continue
            if needle and item["inline_content"] is None:
                visible = {
                    key: value
                    for key, value in item.items()
                    if key not in {"id", "inline_content", "matched_in_content"}
                }
                item["matched_in_content"] = needle not in _json_text(visible).casefold()
            selected.append(item)
        return selected

    def list_events(
        self,
        *,
        page: int,
        page_size: int,
        started_at: datetime,
        ended_at: datetime,
        sources: set[EventSource],
        levels: set[EventLevel],
        query: str,
    ) -> dict[str, object]:
        selected_sources = sources or set(_SOURCE_RANK)
        items: list[dict[str, object]] = []
        started_at = started_at.astimezone(timezone.utc)
        ended_at = ended_at.astimezone(timezone.utc)
        needle = query.casefold()
        if "system" in selected_sources:
            items.extend(
                self._public_items(
                    self._system_events.public_records(),
                    make_item=self._system_item,
                    levels=levels,
                    needle=needle,
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )
        if "runtime" in selected_sources:
            records = [dict(value) for value in self._diagnostics.snapshot()["entries"]]
            items.extend(
                self._public_items(
                    records,
                    make_item=self._runtime_item,
                    levels=levels,
                    needle=needle,
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )

        items.sort(key=self._key, reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    @staticmethod
    def _public_record_matches(
        record: dict[str, object],
        *,
        occurred_at_key: str,
        level_key: str,
        levels: set[EventLevel],
        needle: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> bool:
        timestamp = EventFeedService._timestamp(record[occurred_at_key])
        if timestamp < started_at or timestamp > ended_at:
            return False
        if levels and record.get(level_key) not in levels:
            return False
        return not needle or needle in _json_text(record).casefold()

    def delete_matching(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        sources: set[EventSource],
        levels: set[EventLevel],
        query: str,
    ) -> dict[str, int]:
        selected_sources = sources or set(_SOURCE_RANK)
        started_at = started_at.astimezone(timezone.utc)
        ended_at = ended_at.astimezone(timezone.utc)
        deleted = 0
        needle = query.casefold()

        def matches_system(record: dict[str, object]) -> bool:
            return self._public_record_matches(
                record,
                occurred_at_key="timestamp",
                level_key="level",
                levels=levels,
                needle=needle,
                started_at=started_at,
                ended_at=ended_at,
            )
        def matches_runtime(record: dict[str, object]) -> bool:
            return self._public_record_matches(
                record,
                occurred_at_key="occurred_at",
                level_key="severity",
                levels=levels,
                needle=needle,
                started_at=started_at,
                ended_at=ended_at,
            )

        if "system" in selected_sources:
            deleted += self._system_events.delete_public_records(matches_system)
        if "runtime" in selected_sources:
            deleted += self._diagnostics.delete_entries(matches_runtime)
        return {"deleted": deleted}

    def _system_record(self, item_id: str) -> dict[str, object] | None:
        return next(
            (
                record
                for record in self._system_events.public_records()
                if _public_id(record) == item_id
            ),
            None,
        )

    def _runtime_record(self, item_id: str) -> dict[str, object] | None:
        return next(
            (
                dict(record)
                for record in self._diagnostics.snapshot()["entries"]
                if record.get("diagnostic_id") == item_id
            ),
            None,
        )

    def download(
        self,
        source: EventSource,
        item_id: str,
    ) -> tuple[bytes | Path, str, str] | None:
        if source == "system":
            entry = self._system_record(item_id)
            timestamp_key = "timestamp"
        else:
            entry = self._runtime_record(item_id)
            timestamp_key = "occurred_at"
        if entry is None:
            return None
        timestamp = datetime.fromisoformat(str(entry[timestamp_key])).astimezone(timezone.utc)
        stamp = timestamp.strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
        if source == "runtime":
            detail_path = self._diagnostics.detail_path(item_id)
            if detail_path is not None:
                filename = f"agent-shell-diagnostic-detail-{stamp}-{item_id[:8]}.log"
                return detail_path, filename, "text/plain; charset=utf-8"
        content = (_detail_json(source, entry) + "\n").encode("utf-8")
        filename = f"agent-shell-event-{source}-{stamp}-{item_id[:8]}.json"
        return content, filename, "application/json; charset=utf-8"
