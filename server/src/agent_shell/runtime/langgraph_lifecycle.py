from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from agent_shell.runtime.lifecycle_monitoring_archive import (
    LifecycleMonitoringArchive,
    build_lifecycle_monitoring_archive,
)
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_INPUT_KEY,
    LIFECYCLE_NAMESPACE_ROOT,
    LIFECYCLE_START_ERROR_KEY,
    lifecycle_input_namespace,
)
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


@dataclass(slots=True)
class _LifecycleObservation:
    threads: list[dict[str, Any]]
    thread_groups: list[dict[str, Any]]
    run_entries: list[dict[str, Any]]
    relations: list[GraphRunCallRelation]
    read_failures: list[Exception]
    lifecycle_created_at: str = ""
    start_error: dict[str, Any] | None = None

    @property
    def runs(self) -> list[dict[str, Any]]:
        return [
            entry["run"]
            for entry in self.run_entries
            if isinstance(entry.get("run"), Mapping)
        ]


def _metadata(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _lifecycle_status(
    runs: list[Mapping[str, Any]],
    *,
    unavailable_run_count: int = 0,
    start_error: bool = False,
) -> str:
    if start_error:
        return "error"
    statuses = [official_status(run) for run in runs]
    if not statuses:
        return "unavailable" if unavailable_run_count else "pending"
    if any(status in ACTIVE_RUN_STATUSES for status in statuses):
        return "running"
    if any(status in {"error", "timeout"} for status in statuses):
        return "error"
    if any(status == "interrupted" for status in statuses):
        return "interrupted"
    if unavailable_run_count:
        return "unavailable"
    return "success"


def _run_subject(run: object) -> dict[str, str] | None:
    metadata = _metadata(_metadata(run).get("metadata"))
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


def _relation_metadata(relation: GraphRunCallRelation) -> dict[str, str]:
    metadata = {
        "lifecycle_id": relation.lifecycle_id,
        "graph_kind": relation.graph_kind,
        "caller_run_id": relation.caller_run_id,
        "operation_id": relation.operation_id,
    }
    if relation.graph_kind == "agent":
        metadata.update(
            main_agent_id=relation.resource_id,
            main_agent_name=relation.resource_name,
        )
    else:
        metadata.update(
            workflow_id=relation.resource_id,
            workflow_name=relation.resource_name,
        )
    return metadata


def _unavailable(code: str, exc: Exception) -> dict[str, str]:
    return {
        "code": code,
        "message": str(exc) or exc.__class__.__name__,
    }


def _is_not_found(exc: Exception) -> bool:
    """Recognize a confirmed public API 404 without depending on SDK internals."""

    response = getattr(exc, "response", None)
    return (
        getattr(exc, "status_code", None) == 404
        or getattr(response, "status_code", None) == 404
    )


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
    async def _thread_runs(client: Any, thread_id: str) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await client.runs.list(thread_id, limit=100, offset=offset)
            runs.extend(dict(run) for run in page)
            if len(page) < 100:
                return runs
            offset += len(page)

    async def _observe_lifecycle(
        self,
        client: Any,
        lifecycle_id: str,
        threads: list[dict[str, Any]],
    ) -> _LifecycleObservation:
        """Group public Thread/Run objects while keeping local failures explicit."""

        relations = await search_lifecycle_run_relations(client, lifecycle_id)
        lifecycle_created_at = ""
        start_error: dict[str, Any] | None = None
        try:
            input_item = await client.store.get_item(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_INPUT_KEY,
            )
            if isinstance(input_item, Mapping):
                lifecycle_created_at = str(input_item.get("created_at") or "")
        except Exception:
            pass
        try:
            error_item = await client.store.get_item(
                lifecycle_input_namespace(lifecycle_id),
                LIFECYCLE_START_ERROR_KEY,
            )
            error_value = (
                error_item.get("value") if isinstance(error_item, Mapping) else None
            )
            if isinstance(error_value, Mapping):
                start_error = dict(error_value)
                lifecycle_created_at = lifecycle_created_at or str(
                    error_item.get("created_at") or ""
                )
        except Exception:
            pass
        relations_by_run = {relation.run_id: relation for relation in relations}
        known_thread_ids = {str(thread.get("thread_id") or "") for thread in threads}
        thread_errors: dict[str, dict[str, str]] = {}
        read_failures: list[Exception] = []
        for thread_id in dict.fromkeys(relation.thread_id for relation in relations):
            if thread_id not in known_thread_ids:
                try:
                    threads.append(dict(await client.threads.get(thread_id)))
                except Exception as exc:
                    thread_errors[thread_id] = _unavailable("thread_unavailable", exc)
                    if not _is_not_found(exc):
                        read_failures.append(exc)
                known_thread_ids.add(thread_id)

        runs_by_thread: dict[str, list[dict[str, Any]]] = {}
        for thread in threads:
            thread_id = str(thread["thread_id"])
            try:
                runs_by_thread[thread_id] = await self._thread_runs(client, thread_id)
            except Exception as exc:
                runs_by_thread[thread_id] = []
                thread_errors[thread_id] = _unavailable("runs_unavailable", exc)
                if not _is_not_found(exc):
                    read_failures.append(exc)

        run_entries: list[dict[str, Any]] = []
        observed_run_ids: set[str] = set()
        for thread_id, runs in runs_by_thread.items():
            for run in runs:
                run_id = str(run.get("run_id") or "")
                relation = relations_by_run.get(run_id)
                if relation is not None:
                    run["metadata"] = {
                        **_relation_metadata(relation),
                        **_metadata(run.get("metadata")),
                    }
                run_entries.append(
                    {
                        "run_id": run_id,
                        "run": run,
                        "relation": (
                            relation.model_dump(mode="json")
                            if relation is not None
                            else None
                        ),
                        "error": None,
                    }
                )
                observed_run_ids.add(run_id)

        for relation in relations:
            if relation.run_id in observed_run_ids:
                continue
            run: dict[str, Any] | None = None
            error: dict[str, str] | None = None
            try:
                run = dict(await client.runs.get(relation.thread_id, relation.run_id))
                run["metadata"] = {
                    **_relation_metadata(relation),
                    **_metadata(run.get("metadata")),
                }
            except Exception as exc:
                error = _unavailable("run_unavailable", exc)
                if not _is_not_found(exc):
                    read_failures.append(exc)
            run_entries.append(
                {
                    "run_id": relation.run_id,
                    "run": run,
                    "relation": relation.model_dump(mode="json"),
                    "error": error,
                }
            )

        threads_by_id = {
            str(thread.get("thread_id") or ""): thread for thread in threads
        }
        entries_by_thread: dict[str, list[dict[str, Any]]] = {}
        for entry in run_entries:
            relation = entry.get("relation")
            run = entry.get("run")
            thread_id = str(
                (run.get("thread_id") if isinstance(run, Mapping) else "")
                or (relation.get("thread_id") if isinstance(relation, Mapping) else "")
                or ""
            )
            entries_by_thread.setdefault(thread_id, []).append(entry)

        thread_groups = []
        for thread_id in sorted(
            set(threads_by_id) | set(entries_by_thread),
            key=lambda value: (
                str(threads_by_id.get(value, {}).get("created_at") or ""),
                value,
            ),
        ):
            entries = sorted(
                entries_by_thread.get(thread_id, []),
                key=lambda entry: (
                    str((entry.get("run") or {}).get("created_at") or ""),
                    str(entry.get("run_id") or ""),
                ),
            )
            thread_groups.append(
                {
                    "thread_id": thread_id,
                    "thread": threads_by_id.get(thread_id),
                    "runs": entries,
                    "error": thread_errors.get(thread_id),
                }
            )
        return _LifecycleObservation(
            threads=threads,
            thread_groups=thread_groups,
            run_entries=run_entries,
            relations=relations,
            read_failures=read_failures,
            lifecycle_created_at=lifecycle_created_at,
            start_error=start_error,
        )

    @staticmethod
    def _summary(
        lifecycle_id: str,
        observation: _LifecycleObservation,
    ) -> dict[str, Any]:
        threads = observation.threads
        runs = observation.runs
        metadata = [_metadata(thread.get("metadata")) for thread in threads]
        created_values = [str(thread.get("created_at") or "") for thread in threads]
        if observation.lifecycle_created_at:
            created_values.append(observation.lifecycle_created_at)
        updated_values = [str(thread.get("updated_at") or "") for thread in threads]
        if observation.start_error:
            updated_values.append(str(observation.start_error.get("occurred_at") or ""))
        subjects_by_identity: dict[tuple[str, str], dict[str, str]] = {}
        for entry in sorted(
            observation.run_entries,
            key=lambda item: (
                str((item.get("run") or {}).get("updated_at") or ""),
                str((item.get("run") or {}).get("created_at") or ""),
                str(item.get("run_id") or ""),
            ),
        ):
            run = entry.get("run")
            subject = _run_subject(run)
            if subject is None and isinstance(entry.get("relation"), Mapping):
                subject = _run_subject(
                    {"metadata": _relation_metadata(
                        GraphRunCallRelation.model_validate(entry["relation"])
                    )}
                )
            if subject is not None:
                subjects_by_identity[(subject["graph_kind"], subject["id"])] = subject
        if observation.start_error:
            graph_kind = str(observation.start_error.get("graph_kind") or "")
            subject_id = str(observation.start_error.get("subject_id") or "")
            if graph_kind in {"agent", "workflow"} and subject_id:
                subjects_by_identity[(graph_kind, subject_id)] = {
                    "graph_kind": graph_kind,
                    "id": subject_id,
                    "name": str(observation.start_error.get("subject_name") or ""),
                }
        subjects = sorted(
            subjects_by_identity.values(),
            key=lambda subject: (
                subject["graph_kind"].casefold(),
                subject["name"].casefold(),
                subject["id"].casefold(),
            ),
        )
        statuses = [official_status(run) for run in runs]
        unavailable_run_count = sum(
            not isinstance(entry.get("run"), Mapping)
            for entry in observation.run_entries
        )
        return {
            "lifecycle_id": lifecycle_id,
            "request_id": next(
                (str(item.get("request_id")) for item in metadata if item.get("request_id")),
                str((observation.start_error or {}).get("request_id") or ""),
            ),
            "created_at": min(created_values) if created_values else "",
            "updated_at": max(updated_values) if updated_values else "",
            "status": _lifecycle_status(
                runs,
                unavailable_run_count=unavailable_run_count,
                start_error=observation.start_error is not None,
            ),
            "subjects": subjects,
            "start_error": observation.start_error,
            "run_count": len(observation.run_entries),
            "active_run_count": sum(
                status in ACTIVE_RUN_STATUSES for status in statuses
            ),
            "error_run_count": sum(status in {"error", "timeout"} for status in statuses),
        }

    @staticmethod
    async def _lifecycle_namespaces(
        client: Any,
        lifecycle_id: str | None = None,
    ) -> list[list[str]]:
        prefix = [LIFECYCLE_NAMESPACE_ROOT]
        if lifecycle_id is not None:
            prefix.append(lifecycle_id)
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
                return namespaces
            offset += len(page)

    async def _store_data(self, client: Any, lifecycle_id: str) -> dict[str, Any]:
        namespaces = await self._lifecycle_namespaces(client, lifecycle_id)
        groups: list[dict[str, Any]] = []
        for namespace in sorted(namespaces):
            items: list[dict[str, Any]] = []
            offset = 0
            while True:
                response = await client.store.search_items(
                    namespace,
                    limit=100,
                    offset=offset,
                )
                page = response.get("items", [])
                items.extend(dict(item) for item in page)
                if len(page) < 100:
                    break
                offset += len(page)
            groups.append({"namespace": namespace, "items": items})
        return {"lifecycle_id": lifecycle_id, "namespaces": groups}

    async def _is_known(self, client: Any, lifecycle_id: str) -> bool:
        if await self._threads(client, lifecycle_id):
            return True
        return bool(await self._lifecycle_namespaces(client, lifecycle_id))

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
            namespaces = await self._lifecycle_namespaces(client)
            for namespace in namespaces:
                if len(namespace) >= 2:
                    grouped.setdefault(str(namespace[1]), [])
            summaries: list[dict[str, Any]] = []
            for lifecycle_id, lifecycle_threads in grouped.items():
                observation = await self._observe_lifecycle(
                    client,
                    lifecycle_id,
                    lifecycle_threads,
                )
                summaries.append(self._summary(lifecycle_id, observation))

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
            observation = await self._observe_lifecycle(client, lifecycle_id, threads)
            if not observation.thread_groups and not await self._lifecycle_namespaces(
                client, lifecycle_id
            ):
                raise LangGraphLifecycleNotFound(lifecycle_id)
        return {
            **self._summary(lifecycle_id, observation),
            "threads": observation.thread_groups,
        }

    async def store(self, lifecycle_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            store = await self._store_data(client, lifecycle_id)
            if not store["namespaces"] and not await self._threads(client, lifecycle_id):
                raise LangGraphLifecycleNotFound(lifecycle_id)
            return store

    async def _require_relation(
        self,
        client: Any,
        lifecycle_id: str,
        run_id: str,
    ) -> GraphRunCallRelation:
        relations = await search_lifecycle_run_relations(client, lifecycle_id)
        relation = next((item for item in relations if item.run_id == run_id), None)
        if relation is None:
            if not await self._is_known(client, lifecycle_id):
                raise LangGraphLifecycleNotFound(lifecycle_id)
            raise LangGraphRunNotFound(run_id)
        return relation

    async def graph(self, lifecycle_id: str, run_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation = await self._require_relation(client, lifecycle_id, run_id)
            try:
                graph = await client.assistants.get_graph(relation.assistant_id)
                error = None
            except Exception as exc:
                graph = None
                error = _unavailable("graph_unavailable", exc)
        return {
            "run_id": run_id,
            "assistant_id": relation.assistant_id,
            "graph": graph,
            "error": error,
        }

    async def state(self, lifecycle_id: str, run_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation = await self._require_relation(client, lifecycle_id, run_id)
            try:
                state = await client.threads.get_state(relation.thread_id)
                error = None
            except Exception as exc:
                state = None
                error = _unavailable("state_unavailable", exc)
        return {
            "run_id": run_id,
            "thread_id": relation.thread_id,
            "state": state,
            "error": error,
        }

    async def history(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        limit: int,
    ) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation = await self._require_relation(client, lifecycle_id, run_id)
            try:
                history = await client.threads.get_history(relation.thread_id, limit=limit)
                error = None
            except Exception as exc:
                history = None
                error = _unavailable("history_unavailable", exc)
        return {
            "run_id": run_id,
            "thread_id": relation.thread_id,
            "history": history,
            "error": error,
        }

    @staticmethod
    async def _full_history(client: Any, thread_id: str) -> list[Mapping[str, Any]]:
        history: list[Mapping[str, Any]] = []
        before: Mapping[str, Any] | None = None
        while True:
            page = await client.threads.get_history(
                thread_id,
                limit=100,
                before=before,
            )
            history.extend(page)
            if len(page) < 100:
                return history
            checkpoint = page[-1].get("checkpoint")
            if not isinstance(checkpoint, Mapping):
                raise RuntimeError("LangGraph history page omits its checkpoint cursor")
            before = checkpoint

    async def export(self, lifecycle_id: str) -> LifecycleMonitoringArchive:
        files: dict[str, Any] = {}
        results: list[dict[str, Any]] = []

        async def capture(
            path: str,
            call: Callable[[], Awaitable[Any]],
        ) -> Any | None:
            try:
                value = await call()
            except Exception as exc:
                results.append(
                    {"path": path, "status": "error", "error": _unavailable("unavailable", exc)}
                )
                return None
            files[path] = value
            results.append({"path": path, "status": "available"})
            return value

        async with self._client_factory() as client:
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle_id, threads)
            namespaces = await self._lifecycle_namespaces(client, lifecycle_id)
            if not observation.thread_groups and not namespaces:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            summary = self._summary(lifecycle_id, observation)
            snapshot = {**summary, "threads": observation.thread_groups}
            files["snapshot.json"] = snapshot
            results.append({"path": "snapshot.json", "status": "available"})
            await capture("store.json", lambda: self._store_data(client, lifecycle_id))

            assistant_ids = sorted(
                {
                    relation.assistant_id
                    for relation in observation.relations
                    if relation.assistant_id
                }
            )
            for assistant_id in assistant_ids:
                path = f"assistants/{quote(assistant_id, safe='')}/graph.json"
                await capture(path, lambda value=assistant_id: client.assistants.get_graph(value))

            for group in observation.thread_groups:
                thread_id = str(group["thread_id"])
                encoded = quote(thread_id, safe="")
                if group.get("thread") is None:
                    results.append(
                        {
                            "path": f"threads/{encoded}",
                            "status": "error",
                            "error": group.get("error") or {
                                "code": "thread_unavailable",
                                "message": "The official Thread is unavailable.",
                            },
                        }
                    )
                    continue
                await capture(
                    f"threads/{encoded}/state.json",
                    lambda value=thread_id: client.threads.get_state(value),
                )
                await capture(
                    f"threads/{encoded}/history.json",
                    lambda value=thread_id: self._full_history(client, value),
                )

        exported_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "schema_version": 1,
            "lifecycle_id": lifecycle_id,
            "exported_at": exported_at,
            "atomic": False,
            "lifecycle_status": summary["status"],
            "files": results,
        }
        return await asyncio.to_thread(
            build_lifecycle_monitoring_archive,
            lifecycle_id,
            manifest,
            files,
        )

    async def cancel_active(self, lifecycle_id: str) -> int:
        cancelled = 0
        async with self._client_factory() as client:
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle_id, threads)
            relations = {
                relation.run_id: relation for relation in observation.relations
            }
            for entry in observation.run_entries:
                run = entry.get("run")
                relation = relations.get(str(entry.get("run_id") or ""))
                if (
                    relation is not None
                    and isinstance(run, Mapping)
                    and official_status(run) in ACTIVE_RUN_STATUSES
                ):
                    await client.runs.cancel(relation.thread_id, relation.run_id, wait=False)
                    cancelled += 1
        return cancelled

    @staticmethod
    async def _delete_store_prefix(client: Any, lifecycle_id: str) -> None:
        prefix = [LIFECYCLE_NAMESPACE_ROOT, lifecycle_id]
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
            observation = await self._observe_lifecycle(client, lifecycle_id, threads)
            if not observation.thread_groups and not await self._lifecycle_namespaces(
                client, lifecycle_id
            ):
                raise LangGraphLifecycleNotFound(lifecycle_id)
            if observation.read_failures:
                raise RuntimeError(
                    "Cannot delete a Lifecycle while its official Thread/Run status "
                    "is unavailable"
                ) from observation.read_failures[0]
            if any(
                official_status(run) in ACTIVE_RUN_STATUSES
                for run in observation.runs
            ):
                raise LangGraphLifecycleActive(lifecycle_id)
            for thread in observation.threads:
                await client.threads.delete(str(thread["thread_id"]))
            await self._delete_store_prefix(client, lifecycle_id)
        return len(observation.threads)

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
