from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from starlette.datastructures import QueryParams


_COLLECTION_PARAMETERS = frozenset({"view", "q", "offset", "limit"})


def configuration_collection_requested(query_params: QueryParams) -> bool:
    """Return whether the caller explicitly requested the collection envelope."""

    return any(name in query_params for name in _COLLECTION_PARAMETERS)


def matches_configuration_query(
    item: dict[str, Any],
    query: str,
    fields: Iterable[str],
) -> bool:
    normalized_query = query.strip().casefold()
    return not normalized_query or any(
        normalized_query in str(item.get(field, "")).casefold()
        for field in fields
    )


def configuration_collection(
    items: list[dict[str, Any]],
    *,
    repository_context: tuple[str, int],
    query: str | None,
    search_fields: Iterable[str],
    offset: int,
    limit: int | None,
) -> dict[str, Any]:
    """Apply the shared public query contract to one configuration collection."""

    fields = tuple(search_fields)
    if query:
        items = [
            item
            for item in items
            if matches_configuration_query(item, query, fields)
        ]
    total = len(items)
    page = items[offset:] if limit is None else items[offset : offset + limit]
    repository_id, repository_revision = repository_context
    return {
        "items": page,
        "total": total,
        "repository_id": repository_id,
        "repository_revision": repository_revision,
    }
