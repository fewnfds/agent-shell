from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue


LIFECYCLE_CONFIGURATION_SCHEMA_VERSION = 1


class FrozenRepositoryConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    root: str
    python_packages_root: str
    skill_packages_root: str
    config: dict[str, JsonValue]


class FrozenResourceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bindings: dict[str, str]
    connections: list[dict[str, JsonValue]]


class LifecycleEntryGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_kind: Literal["agent", "workflow"]
    resource_id: str


class LifecycleConfigurationSnapshot(BaseModel):
    """Persisted, JSON-safe configuration facts for one Lifecycle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = LIFECYCLE_CONFIGURATION_SCHEMA_VERSION
    repository: FrozenRepositoryConfiguration
    model: FrozenResourceConfiguration
    mcp: FrozenResourceConfiguration
    runtime: dict[str, JsonValue]
    entry_graph: LifecycleEntryGraph

    def as_store_value(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "LIFECYCLE_CONFIGURATION_SCHEMA_VERSION",
    "LifecycleConfigurationSnapshot",
    "LifecycleEntryGraph",
]
