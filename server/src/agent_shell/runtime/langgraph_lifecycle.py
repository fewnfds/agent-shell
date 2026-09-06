from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from agent_shell.runtime.run_calls import (
    ACTIVE_RUN_STATUSES,
    GraphRunCallRelation,
    official_status,
    search_lifecycle_run_relations,
)
from agent_shell.storage.workflow_lifecycle_settings import (
    WorkflowLifecycleSettingsStore,
)


class LangGraphLifecycleNotFound(LookupError):
    pass


class LangGraphRunNotFound(LookupError):
    pass


class LangGraphLifecycleActive(RuntimeError):
    pass


def _metadata(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _lifecycle_status(runs: list[Mapping[str, Any]]) -> str:
    statuses = [official_status(run) for run in runs]
    if not statuses:
        return "pending"
    if any(status in ACTIVE_RUN_STATUSES for status in statuses):
        return "running"
    if any(status in {"error", "timeout"} for status in statuses):
        return "error"
    if any(status == "interrupted" for status in statuses):
        return "interrupted"
    return "success"


def _run_subject(run: Mapping[str, Any]) -> dict[str, str] | None:
    metadata = _metadata(run.get("metadata"))
    graph_kind = str(metadata.get("graph_kind") or "")
    if graph_kind == "agent":
        subject_id = str(metadata.get("main_agent_id") or "")
        subject_name = str(metadata.get("main_agent_name") or "")
    elif graph_kind == "workflow":
        subject_id = str(metadata.get("workflow_id") or "")
        subject_name = str(metadata.get("workflow_name") or "")
    else:
        return None
    if not subject_id:
        return None
    return {
        "graph_kind": graph_kind,
        "id": subject_id,
        "name": subject_name,
    }


class LangGraphLifecycleService:
    """Project Lifecycle views from LangGraph's public Thread and Run APIs."""

    def __init__(
        self,
        client_factory: Callable[[], Any],
        settings: WorkflowLifecycleSettingsStore | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._settings = settings

    async def _threads(self, client: Any, lifecycle_id: str | None = None) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await client.threads.search(
                metadata=(
                    {"lifecycle_id": lifecycle_id}
                    if lifecycle_id is not None
                    else None
                ),
                limit=100,
                offset=offset,
            )
            for thread in page:
                metadata = _metadata(thread.get("metadata"))
                if lifecycle_id is None and not metadata.get("lifecycle_id"):
                    continue
                threads.append(dict(thread))
            if len(page) < 100:
                return threads
            offset += len(page)

    @staticmethod
    async def _runs(client: Any, threads: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for thread in threads:
            offset = 0
            thread_id = str(thread["thread_id"])
            while True:
                page = await client.runs.list(thread_id, limit=100, offset=offset)
                runs.extend(dict(run) for run in page)
                if len(page) < 100:
                    break
                offset += len(page)
        return runs

    @staticmethod
    def _summary(
        lifecycle_id: str,
        threads: list[Mapping[str, Any]],
        runs: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        metadata = [_metadata(thread.get("metadata")) for thread in threads]
        created_values = [str(thread.get("created_at") or "") for thread in threads]
        updated_values = [str(thread.get("updated_at") or "") for thread in threads]
        subjects_by_identity: dict[tuple[str, str], dict[str, str]] = {}
        for run in sorted(
            runs,
            key=lambda item: (
                str(item.get("updated_at") or item.get("created_at") or ""),
                str(item.get("run_id") or ""),
            ),
        ):
            subject = _run_subject(run)
            if subject is not None:
                subjects_by_identity[(subject["graph_kind"], subject["id"])] = subject
        subjects = sorted(
            subjects_by_identity.values(),
            key=lambda subject: (
                subject["graph_kind"].casefold(),
                subject["name"].casefold(),
                subject["id"].casefold(),
            ),
        )
        statuses = [official_status(run) for run in runs]
        return {
            "lifecycle_id": lifecycle_id,
            "request_id": next(
                (str(item.get("request_id")) for item in metadata if item.get("request_id")),
                "",
            ),
            "created_at": min(created_values) if created_values else "",
            "updated_at": max(updated_values) if updated_values else "",
            "status": _lifecycle_status(runs),
            "subjects": subjects,
            "run_count": len(runs),
            "active_run_count": sum(
                status in ACTIVE_RUN_STATUSES for status in statuses
            ),
            "error_run_count": sum(status in {"error", "timeout"} for status in statuses),
        }

    async def _list_all(self, query: str = "") -> list[dict[str, Any]]:
        """Return every Lifecycle summary without inventing a product limit."""

        async with self._client_factory() as client:
            threads = await self._threads(client)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for thread in threads:
                lifecycle_id = str(
                    _metadata(thread.get("metadata")).get("lifecycle_id") or ""
                )
                if lifecycle_id:
                    grouped.setdefault(lifecycle_id, []).append(thread)
            summaries: list[dict[str, Any]] = []
            for lifecycle_id, lifecycle_threads in grouped.items():
                runs = await self._runs(client, lifecycle_threads)
                summaries.append(self._summary(lifecycle_id, lifecycle_threads, runs))

        normalized_query = query.strip().casefold()
        if normalized_query:
            summaries = [
                item
                for item in summaries
                if normalized_query
                in " ".join(
                    [
                        str(item["lifecycle_id"]),
                        str(item["request_id"]),
                        *[
                            str(value)
                            for subject in item["subjects"]
                            for value in (
                                subject["graph_kind"],
                                subject["id"],
                                subject["name"],
                            )
                        ],
                    ]
                ).casefold()
            ]
        summaries.sort(
            key=lambda item: (str(item["created_at"]), str(item["lifecycle_id"])),
            reverse=True,
        )
        return summaries

    async def list_page(
        self,
        *,
        page: int,
        page_size: int,
        query: str = "",
    ) -> dict[str, Any]:
        summaries = await self._list_all(query)
        total = len(summaries)
        offset = (page - 1) * page_size
        return {
            "items": summaries[offset : offset + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    async def snapshot(self, lifecycle_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            threads = await self._threads(client, lifecycle_id)
            if not threads:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            runs = await self._runs(client, threads)
        return {
            **self._summary(lifecycle_id, threads, runs),
            "threads": threads,
            "runs": runs,
        }

    async def _require_run(
        self,
        client: Any,
        lifecycle_id: str,
        run_id: str,
    ) -> tuple[GraphRunCallRelation, Mapping[str, Any]]:
        relations = await search_lifecycle_run_relations(client, lifecycle_id)
        relation = next((item for item in relations if item.run_id == run_id), None)
        if relation is None:
            if not await self._threads(client, lifecycle_id):
                raise LangGraphLifecycleNotFound(lifecycle_id)
            raise LangGraphRunNotFound(run_id)
        run = await client.runs.get(relation.thread_id, relation.run_id)
        return relation, run

    async def graph(self, lifecycle_id: str, run_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation, _run = await self._require_run(client, lifecycle_id, run_id)
            graph = await client.assistants.get_graph(relation.assistant_id)
        return {"run_id": run_id, "assistant_id": relation.assistant_id, "graph": graph}

    async def state(self, lifecycle_id: str, run_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation, _run = await self._require_run(client, lifecycle_id, run_id)
            state = await client.threads.get_state(relation.thread_id)
        return {"run_id": run_id, "thread_id": relation.thread_id, "state": state}

    async def history(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        limit: int,
    ) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation, _run = await self._require_run(client, lifecycle_id, run_id)
            history = await client.threads.get_history(relation.thread_id, limit=limit)
        return {"run_id": run_id, "thread_id": relation.thread_id, "history": history}

    async def cancel_active(self, lifecycle_id: str) -> int:
        cancelled = 0
        async with self._client_factory() as client:
            relations = await search_lifecycle_run_relations(client, lifecycle_id)
            for relation in relations:
                run = await client.runs.get(relation.thread_id, relation.run_id)
                if official_status(run) in ACTIVE_RUN_STATUSES:
                    await client.runs.cancel(relation.thread_id, relation.run_id, wait=False)
                    cancelled += 1
        return cancelled

    @staticmethod
    async def _delete_store_prefix(client: Any, lifecycle_id: str) -> None:
        prefix = ["workflow-lifecycle", lifecycle_id]
        namespaces: list[list[str]] = []
        offset = 0
        while True:
            response = await client.store.list_namespaces(
                prefix=prefix,
                limit=100,
                offset=offset,
            )
            page = response.get("namespaces", [])
            namespaces.extend(list(namespace) for namespace in page)
            if len(page) < 100:
                break
            offset += len(page)
        for namespace in namespaces:
            items: list[Mapping[str, Any]] = []
            item_offset = 0
            while True:
                response = await client.store.search_items(
                    namespace,
                    limit=100,
                    offset=item_offset,
                )
                page = response.get("items", [])
                items.extend(page)
                if len(page) < 100:
                    break
                item_offset += len(page)
            for item in items:
                await client.store.delete_item(namespace, str(item["key"]))

    async def delete(self, lifecycle_id: str) -> int:
        async with self._client_factory() as client:
            threads = await self._threads(client, lifecycle_id)
            if not threads:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            runs = await self._runs(client, threads)
            if any(official_status(run) in ACTIVE_RUN_STATUSES for run in runs):
                raise LangGraphLifecycleActive(lifecycle_id)
            for thread in threads:
                await client.threads.delete(str(thread["thread_id"]))
            await self._delete_store_prefix(client, lifecycle_id)
        return len(threads)

    async def delete_matching(self, query: str) -> dict[str, int]:
        items = await self._list_all(query)
        deleted = 0
        skipped_active = 0
        for item in items:
            try:
                await self.delete(str(item["lifecycle_id"]))
            except LangGraphLifecycleActive:
                skipped_active += 1
            else:
                deleted += 1
        return {
            "matched": len(items),
            "deleted": deleted,
            "skipped_active": skipped_active,
        }

    async def enforce_retention(self) -> None:
        if self._settings is None:
            raise RuntimeError("Workflow Lifecycle settings are unavailable")
        retained_lifecycles = self._settings.snapshot()["retained_lifecycles"]
        items = await self._list_all()
        terminal = [
            item
            for item in items
            if item["status"] not in {"pending", "running"}
        ]
        for item in terminal[retained_lifecycles:]:
            await self.delete(str(item["lifecycle_id"]))


__all__ = [
    "LangGraphLifecycleActive",
    "LangGraphLifecycleNotFound",
    "LangGraphLifecycleService",
    "LangGraphRunNotFound",
]
