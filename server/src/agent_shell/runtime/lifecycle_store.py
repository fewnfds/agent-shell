from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


LIFECYCLE_NAMESPACE_ROOT = "workflow-lifecycle"
LIFECYCLE_RECORD_KEY = "lifecycle"
LIFECYCLE_CONFIGURATION_KEY = "snapshot"
LIFECYCLE_INPUT_KEY = "request"
LIFECYCLE_START_ERROR_KEY = "start-error"
LIFECYCLE_RECORD_SCHEMA_VERSION = 1


class LifecycleEntrySubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_kind: Literal["agent", "workflow"]
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class LifecycleRecord(BaseModel):
    """Canonical identity facts written once when a Lifecycle begins."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = LIFECYCLE_RECORD_SCHEMA_VERSION
    lifecycle_id: str = Field(min_length=1)
    request_id: str
    created_at: datetime
    entry_subject: LifecycleEntrySubject

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Lifecycle created_at must include a UTC offset")
        return value.astimezone(timezone.utc)

    def as_store_value(self) -> dict[str, Any]:
        value = self.model_dump(mode="json")
        value["created_at"] = self.created_at.isoformat()
        return value


def _namespace(lifecycle_id: str, *parts: str) -> tuple[str, ...]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, *parts)


def lifecycle_input_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "input")


def lifecycle_record_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "metadata")


def lifecycle_configuration_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "configuration")


def lifecycle_filesystem_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "filesystem")


def lifecycle_runs_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "runs")


__all__ = [
    "LIFECYCLE_CONFIGURATION_KEY",
    "LIFECYCLE_INPUT_KEY",
    "LIFECYCLE_NAMESPACE_ROOT",
    "LIFECYCLE_RECORD_KEY",
    "LIFECYCLE_RECORD_SCHEMA_VERSION",
    "LIFECYCLE_START_ERROR_KEY",
    "LifecycleEntrySubject",
    "LifecycleRecord",
    "lifecycle_configuration_namespace",
    "lifecycle_filesystem_namespace",
    "lifecycle_input_namespace",
    "lifecycle_record_namespace",
    "lifecycle_runs_namespace",
]
