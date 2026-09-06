from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agent_shell.configuration.bundles.archive import BundleArchiveError
from agent_shell.configuration.bundles.contracts import BundleManifest, ImportResolutions
from agent_shell.configuration.bundles.errors import BundleImportError, bundle_issue
from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    iter_configuration_references,
    rewrite_configuration_references,
)
from agent_shell.configuration.identity import (
    name_collision_key,
    new_configuration_id,
)
from agent_shell.contracts import MANAGED_COMPONENT_MODELS
from agent_shell.python_packages.authoring import PACKAGE_COMPONENT_SPECS


@dataclass(frozen=True, slots=True)
class BundleRecordSet:
    entities: tuple[ConfigurationEntity, ...]
    component_types: dict[str, str]
    component_records: dict[str, tuple[str, str, dict[str, Any]]]
    skill_package_owners: set[str]


@dataclass(frozen=True, slots=True)
class IdentityPlan:
    target_ids: dict[str, str]
    names: dict[str, str]
    records: list[dict[str, object]]
    errors: list[dict[str, object]]
    supplied_names: set[str]


def _source_entity(record: Any) -> ConfigurationEntity:
    identity = (
        "component_name"
        if record.kind in {"subagent", "async_subagent"}
        else "name"
    )
    payload = {
        identity: record.name,
        **deepcopy(record.payload),
        "id": record.source_id,
    }
    return ConfigurationEntity(
        id=record.source_id,
        kind=record.kind,
        component_type=record.component_type or "",
        name=record.name,
        payload=payload,
    )


def _matches_reference(target: ConfigurationEntity, reference: Any) -> bool:
    return target.kind == reference.target_kind and (
        target.kind != "component"
        or target.component_type == reference.target_component_type
    )


def _validate_complete_closure(
    records: tuple[ConfigurationEntity, ...],
    root_id: str,
) -> None:
    by_id = {record.id: record for record in records}
    pending = [by_id[root_id]]
    reached: set[str] = set()
    while pending:
        owner = pending.pop()
        if owner.id in reached:
            continue
        reached.add(owner.id)
        for reference in iter_configuration_references(owner):
            target = by_id.get(reference.target_id)
            if target is None:
                raise BundleArchiveError(
                    f"bundle omits reference target at {reference.path}"
                )
            if not _matches_reference(target, reference):
                raise BundleArchiveError(
                    f"bundle reference has the wrong type at {reference.path}"
                )
            pending.append(target)
    if reached != set(by_id):
        raise BundleArchiveError("bundle contains records outside its root closure")


def load_bundle_record_set(manifest: BundleManifest) -> BundleRecordSet:
    entities = tuple(_source_entity(record) for record in manifest.records)
    _validate_complete_closure(entities, manifest.root.source_id)
    component_types = {
        entity.id: entity.component_type
        for entity in entities
        if entity.kind == "component"
    }
    unsupported = sorted(
        set(component_types.values()).difference(MANAGED_COMPONENT_MODELS)
    )
    if unsupported:
        raise BundleArchiveError(
            f"bundle contains unsupported component types: {', '.join(unsupported)}"
        )

    skill_package_owners: set[str] = set()
    component_records: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for entity in entities:
        if entity.kind != "component":
            continue
        if entity.component_type == "model-requirement":
            allowed = {"id", "name", "description"}
            if set(entity.payload) - allowed:
                raise BundleArchiveError(
                    "bundle Model Requirement contains connection fields"
                )
        if entity.component_type in PACKAGE_COMPONENT_SPECS:
            reference = entity.payload.get("python_package")
            if not isinstance(reference, dict) or reference.get("folder") != entity.name:
                raise BundleArchiveError(
                    "bundle Python package folder does not match its Component name"
                )
        payload = deepcopy(entity.payload)
        payload.pop("id", None)
        payload.pop("name", None)
        component_records[entity.id] = (
            entity.component_type,
            entity.name,
            payload,
        )
        if entity.component_type == "skill":
            reference = entity.payload.get("skill_package")
            if not isinstance(reference, dict) or reference.get("folder") != entity.name:
                raise BundleArchiveError(
                    "bundle Skill package folder does not match its Component name"
                )
            skill_package_owners.add(entity.id)
    return BundleRecordSet(
        entities=entities,
        component_types=component_types,
        component_records=component_records,
        skill_package_owners=skill_package_owners,
    )


def _scope(entity: ConfigurationEntity) -> tuple[str, str]:
    return (
        entity.kind,
        entity.component_type if entity.kind == "component" else "",
    )


def _entity_name_key(entity: ConfigurationEntity, value: str) -> str:
    return value if entity.kind == "workflow" else name_collision_key(value)


def _next_name(entity: ConfigurationEntity, used: set[str]) -> str:
    original = entity.name
    if _entity_name_key(entity, original) not in used:
        return original
    index = 1
    while True:
        suffix = " (imported)" if index == 1 else f" (imported {index})"
        candidate = original[: 120 - len(suffix)].rstrip() + suffix
        if _entity_name_key(entity, candidate) not in used:
            return candidate
        index += 1


def plan_identities(
    records: BundleRecordSet,
    existing: tuple[ConfigurationEntity, ...],
    resolutions: ImportResolutions | None,
    *,
    require_resolved: bool,
    forbidden_ids: set[str] | None = None,
) -> IdentityPlan:
    existing_ids = {entity.id for entity in existing}
    existing_ids.update(forbidden_ids or ())
    source_ids = {entity.id for entity in records.entities}
    if resolutions is None:
        target_ids: dict[str, str] = {}
        for source_id in sorted(source_ids):
            target_id = new_configuration_id()
            while target_id in existing_ids or target_id in source_ids:
                target_id = new_configuration_id()
            target_ids[source_id] = target_id
    else:
        target_ids = dict(resolutions.target_ids)
        values = list(target_ids.values())
        if set(target_ids) != source_ids:
            raise BundleImportError(
                "import target UUID map must exactly match bundle source records"
            )
        if (
            len(values) != len(set(values))
            or set(values).intersection(existing_ids)
            or set(values).intersection(source_ids)
        ):
            raise BundleImportError(
                "import target UUID values must be new and globally unique"
            )

    used_names: dict[tuple[str, str], set[str]] = {}
    for entity in existing:
        used_names.setdefault(_scope(entity), set()).add(
            _entity_name_key(entity, entity.name)
        )
    supplied = dict(resolutions.names) if resolutions is not None else {}
    if not set(supplied).issubset(source_ids):
        raise BundleImportError("import names contain unknown source UUIDs")

    names: dict[str, str] = {}
    plans: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for entity in records.entities:
        used = used_names.setdefault(_scope(entity), set())
        suggested = _next_name(entity, used)
        requires_confirmation = suggested != entity.name
        selected = supplied.get(entity.id, suggested)
        path = (
            "component_name"
            if entity.kind in {"subagent", "async_subagent"}
            else "name"
        )
        if requires_confirmation and require_resolved and entity.id not in supplied:
            errors.append(
                bundle_issue(
                    "configuration_name_confirmation_required",
                    "The imported configuration name must be confirmed.",
                    source_id=entity.id,
                    path=path,
                )
            )
        if _entity_name_key(entity, selected) in used:
            errors.append(
                bundle_issue(
                    "configuration_name_conflict",
                    "The selected imported configuration name already exists in its scope.",
                    source_id=entity.id,
                    path=path,
                )
            )
        names[entity.id] = selected
        used.add(_entity_name_key(entity, selected))
        plans.append(
            {
                "source_id": entity.id,
                "target_id": target_ids[entity.id],
                "kind": entity.kind,
                "type": entity.component_type or None,
                "original_name": entity.name,
                "suggested_name": suggested,
                "selected_name": selected,
                "requires_confirmation": requires_confirmation,
            }
        )
    return IdentityPlan(
        target_ids=target_ids,
        names=names,
        records=plans,
        errors=errors,
        supplied_names=set(supplied),
    )


def transform_bundle_records(
    records: BundleRecordSet,
    identities: IdentityPlan,
    component_payloads: dict[str, dict[str, Any]],
) -> tuple[ConfigurationEntity, ...]:
    transformed: list[ConfigurationEntity] = []
    for source in records.entities:
        rewritten = rewrite_configuration_references(source, identities.target_ids)
        rewritten["id"] = identities.target_ids[source.id]
        identity = (
            "component_name"
            if source.kind in {"subagent", "async_subagent"}
            else "name"
        )
        rewritten[identity] = identities.names[source.id]
        if source.kind == "component":
            rewritten.update(component_payloads[source.id])
            if source.component_type in PACKAGE_COMPONENT_SPECS:
                rewritten["python_package"]["folder"] = identities.names[source.id]
            if source.component_type == "skill":
                rewritten["skill_package"]["folder"] = identities.names[source.id]
        if source.kind == "workflow":
            rewritten["enabled"] = False
        transformed.append(
            ConfigurationEntity(
                id=identities.target_ids[source.id],
                kind=source.kind,
                component_type=source.component_type,
                name=identities.names[source.id],
                payload=rewritten,
            )
        )
    return tuple(transformed)


__all__ = [
    "BundleRecordSet",
    "IdentityPlan",
    "load_bundle_record_set",
    "plan_identities",
    "transform_bundle_records",
]
