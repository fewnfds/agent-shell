from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


ConfigurationEntityKind = Literal[
    "component",
    "main_agent",
    "subagent",
    "workflow",
]


@dataclass(frozen=True, slots=True)
class ConfigurationEntity:
    id: str
    kind: ConfigurationEntityKind
    name: str
    payload: dict[str, Any]
    component_type: str = ""


@dataclass(frozen=True, slots=True)
class ConfigurationReference:
    owner_id: str
    owner_kind: ConfigurationEntityKind
    owner_name: str
    path: str
    target_id: str
    target_kind: ConfigurationEntityKind
    target_component_type: str = ""
    location: tuple[str | int, ...] = ()


def _records(value: object) -> Iterator[dict[str, Any]]:
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            yield item


def iter_configuration_entities(
    config: dict[str, Any],
) -> Iterator[ConfigurationEntity]:
    components = config.get("components", {})
    if isinstance(components, dict):
        for component_type, values in components.items():
            for record in _records(values):
                yield ConfigurationEntity(
                    id=str(record.get("id", "")),
                    kind="component",
                    component_type=str(component_type),
                    name=str(record.get("name", "")),
                    payload=record,
                )
    for record in _records(config.get("main_agents", [])):
        yield ConfigurationEntity(
            id=str(record.get("id", "")),
            kind="main_agent",
            name=str(record.get("name", "")),
            payload=record,
        )
    for record in _records(config.get("subagents", [])):
        yield ConfigurationEntity(
            id=str(record.get("id", "")),
            kind="subagent",
            name=str(record.get("component_name", "")),
            payload=record,
        )
    for record in _records(config.get("workflows", [])):
        yield ConfigurationEntity(
            id=str(record.get("id", "")),
            kind="workflow",
            name=str(record.get("name", "")),
            payload=record,
        )


def _target_id(value: object) -> str:
    return value if isinstance(value, str) else ""


def _reference(
    owner: ConfigurationEntity,
    *,
    path: str,
    target_id: object,
    target_kind: ConfigurationEntityKind,
    target_component_type: str = "",
    location: tuple[str | int, ...],
) -> ConfigurationReference:
    return ConfigurationReference(
        owner_id=owner.id,
        owner_kind=owner.kind,
        owner_name=owner.name,
        path=path,
        target_id=_target_id(target_id),
        target_kind=target_kind,
        target_component_type=target_component_type,
        location=location,
    )


def _main_agent_references(
    owner: ConfigurationEntity,
) -> Iterator[ConfigurationReference]:
    payload = owner.payload
    for index, item in enumerate(_records(payload.get("capability_refs", []))):
        yield _reference(
            owner,
            path=f"capability_refs[{index}].block_id",
            target_id=item.get("block_id"),
            target_kind="component",
            target_component_type=str(item.get("type", "")),
            location=("capability_refs", index, "block_id"),
        )
    for index, item in enumerate(_records(payload.get("tool_refs", []))):
        yield _reference(
            owner,
            path=f"tool_refs[{index}].tool_id",
            target_id=item.get("tool_id"),
            target_kind="component",
            target_component_type="custom-tool",
            location=("tool_refs", index, "tool_id"),
        )
    for index, item in enumerate(_records(payload.get("middleware_refs", []))):
        yield _reference(
            owner,
            path=f"middleware_refs[{index}].middleware_id",
            target_id=item.get("middleware_id"),
            target_kind="component",
            target_component_type="custom-middleware",
            location=("middleware_refs", index, "middleware_id"),
        )
    for index, item in enumerate(_records(payload.get("subagents", []))):
        yield _reference(
            owner,
            path=f"subagents[{index}].subagent_id",
            target_id=item.get("subagent_id"),
            target_kind="subagent",
            location=("subagents", index, "subagent_id"),
        )


def _component_references(
    owner: ConfigurationEntity,
) -> Iterator[ConfigurationReference]:
    if owner.component_type != "filesystem":
        return
    skill_package_id = owner.payload.get("skill_package_id")
    if skill_package_id is None:
        return
    yield _reference(
        owner,
        path="skill_package_id",
        target_id=skill_package_id,
        target_kind="component",
        target_component_type="skill",
        location=("skill_package_id",),
    )


def _subagent_references(
    owner: ConfigurationEntity,
) -> Iterator[ConfigurationReference]:
    settings = owner.payload.get("settings", {})
    if not isinstance(settings, dict):
        return
    for index, item in enumerate(
        _records(settings.get("capability_overrides", []))
    ):
        if item.get("mode") != "replace":
            continue
        yield _reference(
            owner,
            path=f"settings.capability_overrides[{index}].block_id",
            target_id=item.get("block_id"),
            target_kind="component",
            target_component_type=str(item.get("type", "")),
            location=("settings", "capability_overrides", index, "block_id"),
        )
    for index, item in enumerate(_records(settings.get("tool_refs", []))):
        yield _reference(
            owner,
            path=f"settings.tool_refs[{index}].tool_id",
            target_id=item.get("tool_id"),
            target_kind="component",
            target_component_type="custom-tool",
            location=("settings", "tool_refs", index, "tool_id"),
        )
    for index, item in enumerate(_records(settings.get("middleware_refs", []))):
        yield _reference(
            owner,
            path=f"settings.middleware_refs[{index}].middleware_id",
            target_id=item.get("middleware_id"),
            target_kind="component",
            target_component_type="custom-middleware",
            location=("settings", "middleware_refs", index, "middleware_id"),
        )


def _workflow_references(
    owner: ConfigurationEntity,
) -> Iterator[ConfigurationReference]:
    payload = owner.payload
    checkpointer_id = payload.get("checkpointer_id")
    if checkpointer_id is not None:
        yield _reference(
            owner,
            path="checkpointer_id",
            target_id=checkpointer_id,
            target_kind="component",
            target_component_type="checkpointer",
            location=("checkpointer_id",),
        )
    event_output_id = payload.get("workflow_event_output_id")
    if event_output_id is not None:
        yield _reference(
            owner,
            path="workflow_event_output_id",
            target_id=event_output_id,
            target_kind="component",
            target_component_type="workflow-event-output",
            location=("workflow_event_output_id",),
        )
    definition = payload.get("definition", {})
    if not isinstance(definition, dict):
        return
    for index, node in enumerate(_records(definition.get("nodes", []))):
        config = node.get("config", {})
        if not isinstance(config, dict):
            continue
        node_type = node.get("type")
        if node_type == "agent":
            field, target_kind, component_type = (
                "main_agent_id",
                "main_agent",
                "",
            )
        elif node_type == "command":
            field, target_kind, component_type = (
                "command_id",
                "component",
                "command",
            )
        elif node_type == "task-dispatcher":
            field, target_kind, component_type = (
                "task_dispatcher_id",
                "component",
                "task-dispatcher",
            )
        else:
            continue
        yield _reference(
            owner,
            path=f"definition.nodes[{index}].config.{field}",
            target_id=config.get(field),
            target_kind=target_kind,
            target_component_type=component_type,
            location=("definition", "nodes", index, "config", field),
        )


def iter_configuration_references(
    owner: ConfigurationEntity,
) -> Iterator[ConfigurationReference]:
    if owner.kind == "component":
        yield from _component_references(owner)
    elif owner.kind == "main_agent":
        yield from _main_agent_references(owner)
    elif owner.kind == "subagent":
        yield from _subagent_references(owner)
    elif owner.kind == "workflow":
        yield from _workflow_references(owner)


def rewrite_configuration_references(
    owner: ConfigurationEntity,
    target_ids: dict[str, str],
) -> dict[str, Any]:
    """Return an entity payload whose declared references use ``target_ids``."""

    payload = deepcopy(owner.payload)
    for reference in iter_configuration_references(owner):
        target_id = target_ids.get(reference.target_id)
        if target_id is None:
            raise ValueError(
                f"configuration bundle omits reference target {reference.target_id}"
            )
        current: Any = payload
        for segment in reference.location[:-1]:
            current = current[segment]
        current[reference.location[-1]] = target_id
    return payload


__all__ = [
    "ConfigurationEntity",
    "ConfigurationEntityKind",
    "ConfigurationReference",
    "iter_configuration_entities",
    "iter_configuration_references",
    "rewrite_configuration_references",
]
