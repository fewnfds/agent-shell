from __future__ import annotations

import re
from typing import Any

from agent_shell.configuration.dependencies import (
    iter_configuration_entities,
    iter_configuration_references,
)
from agent_shell.configuration.identity import (
    name_collision_key,
    normalize_configuration_name,
    require_configuration_id,
)


_COMPONENT_TYPE = re.compile(r"^[a-z][a-z0-9-]*$")


def _record_list(value: object, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if any(not isinstance(record, dict) for record in value):
        raise ValueError(f"{label} records must be mappings")
    return value


def validate_configuration_snapshot(
    config: dict[str, Any],
    *,
    config_version: int,
) -> None:
    if config.get("config_version") != config_version:
        raise ValueError(
            f"config_version must equal the current version {config_version}"
        )
    components = config.get("components")
    if not isinstance(components, dict):
        raise ValueError("config components must be a mapping")
    for component_type, records in components.items():
        if (
            not isinstance(component_type, str)
            or _COMPONENT_TYPE.fullmatch(component_type) is None
        ):
            raise ValueError("component type keys must be normalized path segments")
        _record_list(records, label=f"components.{component_type}")
    for key in ("main_agents", "subagents", "async_subagents", "workflows"):
        _record_list(config.get(key), label=key)

    seen_ids: dict[str, str] = {}
    seen_names: dict[tuple[str, str], dict[str, str]] = {}
    mcp_namespaces: dict[str, str] = {}
    for entity in iter_configuration_entities(config):
        entity_id = require_configuration_id(
            entity.payload.get("id"),
            label=f"{entity.kind} id",
        )
        previous = seen_ids.get(entity_id)
        if previous is not None:
            raise ValueError(
                f"configuration id {entity_id} is duplicated by {previous} and "
                f"{entity.kind}"
            )
        seen_ids[entity_id] = entity.kind

        identity_field = (
            "component_name"
            if entity.kind in {"subagent", "async_subagent"}
            else "name"
        )
        raw_name = entity.payload.get(identity_field)
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(
                f"{entity.kind} {entity_id} must have a non-empty {identity_field}"
            )
        normalized_name = normalize_configuration_name(
            raw_name,
            label=f"{entity.kind} {entity_id} {identity_field}",
        )
        if normalized_name != raw_name:
            raise ValueError(
                f"{entity.kind} {entity_id} must use a normalized {identity_field}"
            )
        scope = (
            entity.kind,
            entity.component_type if entity.kind == "component" else "",
        )
        collision_key = (
            raw_name if entity.kind == "workflow" else name_collision_key(raw_name)
        )
        scoped_names = seen_names.setdefault(scope, {})
        previous_name_id = scoped_names.get(collision_key)
        if previous_name_id is not None:
            raise ValueError(
                f"configuration name {raw_name!r} conflicts with {previous_name_id} "
                f"in the {scope[0]} scope"
            )
        scoped_names[collision_key] = entity_id

        if entity.kind == "component" and entity.component_type == "mcp-requirement":
            namespace = entity.payload.get("namespace")
            if isinstance(namespace, str):
                previous_namespace_id = mcp_namespaces.get(namespace)
                if previous_namespace_id is not None:
                    raise ValueError(
                        f"MCP namespace {namespace!r} conflicts with {previous_namespace_id}"
                    )
                mcp_namespaces[namespace] = entity_id

        for reference in iter_configuration_references(entity):
            require_configuration_id(
                reference.target_id,
                label=f"{entity.kind} {entity_id} reference {reference.path}",
            )


__all__ = ["validate_configuration_snapshot"]
