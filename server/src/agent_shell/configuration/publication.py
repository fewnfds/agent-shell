from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal

from agent_shell.configuration.dependencies import (
    iter_configuration_entities,
    iter_configuration_references,
)


PublicationKind = Literal["main_agent", "workflow"]


@dataclass(frozen=True, slots=True)
class PublicationDemotion:
    kind: PublicationKind
    entity_id: str


def demote_dependent_publications(
    config: dict,
    removed_ids: set[str],
) -> tuple[PublicationDemotion, ...]:
    """Demote published graphs transitively affected by declared deletions."""

    if not removed_ids:
        return ()
    entities = tuple(iter_configuration_entities(config))
    reverse_references: dict[str, set[str]] = defaultdict(set)
    for owner in entities:
        for reference in iter_configuration_references(owner):
            reverse_references[reference.target_id].add(owner.id)

    affected = set(removed_ids)
    pending = deque(removed_ids)
    while pending:
        target_id = pending.popleft()
        for owner_id in reverse_references.get(target_id, ()):
            if owner_id in affected:
                continue
            affected.add(owner_id)
            pending.append(owner_id)

    demoted: list[PublicationDemotion] = []
    for entity in entities:
        if (
            entity.id in affected
            and entity.id not in removed_ids
            and entity.kind in {"main_agent", "workflow"}
            and entity.payload.get("enabled") is True
        ):
            entity.payload["enabled"] = False
            demoted.append(
                PublicationDemotion(
                    kind=entity.kind,
                    entity_id=entity.id,
                )
            )
    return tuple(sorted(demoted, key=lambda item: (item.kind, item.entity_id)))


__all__ = ["PublicationDemotion", "demote_dependent_publications"]
