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
from agent_shell.runtime.lifecycle_configuration import LifecycleConfigurationSnapshot
from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_CONFIGURATION_KEY,
    LIFECYCLE_NAMESPACE_ROOT,
    LIFECYCLE_RECORD_KEY,
    LIFECYCLE_START_ERROR_KEY,
    LifecycleRecord,
    lifecycle_configuration_namespace,
    lifecycle_input_namespace,
    lifecycle_record_namespace,
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
from agent_shell.workflow.catalog import node_catalog_payload


class LangGraphLifecycleNotFound(LookupError):
    pass


class LangGraphRunNotFound(LookupError):
    pass


class LangGraphLifecycleActive(RuntimeError):
    pass


@dataclass(slots=True)
class _LifecycleObservation:
    lifecycle: LifecycleRecord
    threads: list[dict[str, Any]]
    thread_groups: list[dict[str, Any]]
    run_entries: list[dict[str, Any]]
    relations: list[GraphRunCallRelation]
    read_failures: list[Exception]
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


def _utc_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    timestamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value))
    )
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


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

    @staticmethod
    async def _configuration_snapshot(
        client: Any,
        lifecycle_id: str,
    ) -> LifecycleConfigurationSnapshot:
        item = await client.store.get_item(
            lifecycle_configuration_namespace(lifecycle_id),
            LIFECYCLE_CONFIGURATION_KEY,
        )
        value = item.get("value") if isinstance(item, Mapping) else None
        if not isinstance(value, Mapping):
            raise RuntimeError("The Lifecycle configuration snapshot is unavailable.")
        return LifecycleConfigurationSnapshot.model_validate(value)

    @staticmethod
    def _workflow_document(
        snapshot: LifecycleConfigurationSnapshot,
        workflow_id: str,
    ) -> dict[str, Any]:
        workflows = snapshot.repository.config.get("workflows")
        if not isinstance(workflows, list):
            raise ValueError("The Lifecycle Workflow snapshot is invalid.")
        workflow = next(
            (
                item
                for item in workflows
                if isinstance(item, dict) and item.get("id") == workflow_id
            ),
            None,
        )
        if workflow is None:
            raise LookupError(
                f"Workflow {workflow_id} is not in the Lifecycle snapshot."
            )
        definition = workflow.get("definition")
        layout = workflow.get("layout")
        if not isinstance(definition, dict) or not isinstance(layout, dict):
            raise ValueError("The Lifecycle Workflow document is invalid.")
        return {"definition": definition, "layout": layout}

    @staticmethod
    def _workflow_commands(
        snapshot: LifecycleConfigurationSnapshot,
    ) -> list[dict[str, str]]:
        components = snapshot.repository.config.get("components")
        commands = components.get("command") if isinstance(components, dict) else None
        if not isinstance(commands, list):
            return []
        return [
            {"id": str(item["id"]), "name": str(item["name"])}
            for item in commands
            if isinstance(item, dict) and "id" in item and "name" in item
        ]

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
        lifecycle: LifecycleRecord,
        threads: list[dict[str, Any]],
    ) -> _LifecycleObservation:
        """Group public Thread/Run objects while keeping local failures explicit."""

        lifecycle_id = lifecycle.lifecycle_id
        relations = await search_lifecycle_run_relations(client, lifecycle_id)
        start_error: dict[str, Any] | None = None
        error_item = await client.store.get_item(
            lifecycle_input_namespace(lifecycle_id),
            LIFECYCLE_START_ERROR_KEY,
        )
        if isinstance(error_item, Mapping):
            error_value = error_item.get("value")
            if not isinstance(error_value, Mapping):
                raise RuntimeError("Lifecycle start-error record is invalid")
            start_error = dict(error_value)
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
            lifecycle=lifecycle,
            threads=threads,
            thread_groups=thread_groups,
            run_entries=run_entries,
            relations=relations,
            read_failures=read_failures,
            start_error=start_error,
        )

    @staticmethod
    def _summary(
        observation: _LifecycleObservation,
    ) -> dict[str, Any]:
        lifecycle = observation.lifecycle
        lifecycle_id = lifecycle.lifecycle_id
        threads = observation.threads
        runs = observation.runs
        updated_values = [lifecycle.created_at]
        updated_values.extend(
            timestamp
            for thread in threads
            if (timestamp := _utc_datetime(thread.get("updated_at"))) is not None
        )
        if observation.start_error:
            start_error_timestamp = _utc_datetime(
                observation.start_error.get("occurred_at")
            )
            if start_error_timestamp is not None:
                updated_values.append(start_error_timestamp)
        entry_subject = lifecycle.entry_subject.model_dump()
        subjects_by_identity = {
            (entry_subject["graph_kind"], entry_subject["id"]): entry_subject
        }
        for relation in observation.relations:
            subject = {
                "graph_kind": relation.graph_kind,
                "id": relation.resource_id,
                "name": relation.resource_name,
            }
            identity = (relation.graph_kind, relation.resource_id)
            existing = subjects_by_identity.get(identity)
            if existing is not None and existing != subject:
                raise RuntimeError("Lifecycle Graph subject identity is inconsistent")
            subjects_by_identity[identity] = subject
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
            "request_id": lifecycle.request_id,
            "created_at": lifecycle.created_at.isoformat(),
            "updated_at": max(updated_values).isoformat() if updated_values else "",
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
                break
            offset += len(page)
        populated: list[list[str]] = []
        for namespace in namespaces:
            response = await client.store.search_items(
                namespace,
                limit=1,
                offset=0,
            )
            if response.get("items"):
                populated.append(namespace)
        return populated

    @staticmethod
    async def _lifecycle_record(
        client: Any,
        lifecycle_id: str,
    ) -> LifecycleRecord | None:
        item = await client.store.get_item(
            lifecycle_record_namespace(lifecycle_id),
            LIFECYCLE_RECORD_KEY,
        )
        if not isinstance(item, Mapping):
            return None
        record = LifecycleRecord.model_validate(item.get("value"))
        if record.lifecycle_id != lifecycle_id:
            raise RuntimeError("Lifecycle record identity does not match its namespace")
        return record

    async def _lifecycle_records(self, client: Any) -> dict[str, LifecycleRecord]:
        namespaces: list[list[str]] = []
        offset = 0
        while True:
            response = await client.store.list_namespaces(
                prefix=[LIFECYCLE_NAMESPACE_ROOT],
                limit=100,
                offset=offset,
            )
            page = response.get("namespaces", [])
            namespaces.extend(list(namespace) for namespace in page)
            if len(page) < 100:
                break
            offset += len(page)
        lifecycle_ids = dict.fromkeys(
            str(namespace[1])
            for namespace in namespaces
            if len(namespace) == 3
            and tuple(namespace)
            == lifecycle_record_namespace(str(namespace[1]))
        )
        records: dict[str, LifecycleRecord] = {}
        for lifecycle_id in lifecycle_ids:
            record = await self._lifecycle_record(client, lifecycle_id)
            if record is not None:
                records[lifecycle_id] = record
        return records

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
        return await self._lifecycle_record(client, lifecycle_id) is not None

    async def _list_all(self, query: str = "") -> list[dict[str, Any]]:
        """Return every Lifecycle summary without inventing a product limit."""

        async with self._client_factory() as client:
            records = await self._lifecycle_records(client)
            threads = await self._threads(client)
            grouped: dict[str, list[dict[str, Any]]] = {
                lifecycle_id: [] for lifecycle_id in records
            }
            for thread in threads:
                lifecycle_id = str(
                    _metadata(thread.get("metadata")).get("lifecycle_id") or ""
                )
                if lifecycle_id in records:
                    grouped.setdefault(lifecycle_id, []).append(thread)
            summaries: list[dict[str, Any]] = []
            for lifecycle_id, lifecycle_threads in grouped.items():
                observation = await self._observe_lifecycle(
                    client,
                    records[lifecycle_id],
                    lifecycle_threads,
                )
                summaries.append(self._summary(observation))

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
            lifecycle = await self._lifecycle_record(client, lifecycle_id)
            if lifecycle is None:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle, threads)
        return {
            **self._summary(observation),
            "threads": observation.thread_groups,
        }

    async def store(self, lifecycle_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            if not await self._is_known(client, lifecycle_id):
                raise LangGraphLifecycleNotFound(lifecycle_id)
            store = await self._store_data(client, lifecycle_id)
            return store

    async def _require_relation(
        self,
        client: Any,
        lifecycle_id: str,
        run_id: str,
    ) -> GraphRunCallRelation:
        if not await self._is_known(client, lifecycle_id):
            raise LangGraphLifecycleNotFound(lifecycle_id)
        relations = await search_lifecycle_run_relations(client, lifecycle_id)
        relation = next((item for item in relations if item.run_id == run_id), None)
        if relation is None:
            raise LangGraphRunNotFound(run_id)
        return relation

    async def graph(self, lifecycle_id: str, run_id: str) -> dict[str, Any]:
        async with self._client_factory() as client:
            relation = await self._require_relation(client, lifecycle_id, run_id)
            try:
                if relation.graph_kind == "workflow":
                    snapshot = await self._configuration_snapshot(client, lifecycle_id)
                    graph = None
                    workflow_document = self._workflow_document(
                        snapshot,
                        relation.resource_id,
                    )
                    workflow_node_catalog = node_catalog_payload()
                    workflow_commands = self._workflow_commands(snapshot)
                else:
                    graph = await client.assistants.get_graph(relation.assistant_id)
                    workflow_document = None
                    workflow_node_catalog = None
                    workflow_commands = None
                error = None
            except Exception as exc:
                graph = None
                workflow_document = None
                workflow_node_catalog = None
                workflow_commands = None
                error = _unavailable("graph_unavailable", exc)
        return {
            "run_id": run_id,
            "assistant_id": relation.assistant_id,
            "graph_kind": relation.graph_kind,
            "graph": graph,
            "workflow_document": workflow_document,
            "workflow_node_catalog": workflow_node_catalog,
            "workflow_commands": workflow_commands,
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
            lifecycle = await self._lifecycle_record(client, lifecycle_id)
            if lifecycle is None:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle, threads)
            summary = self._summary(observation)
            snapshot = {**summary, "threads": observation.thread_groups}
            files["snapshot.json"] = snapshot
            results.append({"path": "snapshot.json", "status": "available"})
            await capture("store.json", lambda: self._store_data(client, lifecycle_id))

            configuration = await capture(
                "configuration/snapshot.json",
                lambda: self._configuration_snapshot(client, lifecycle_id),
            )
            if isinstance(configuration, LifecycleConfigurationSnapshot):
                files["configuration/snapshot.json"] = configuration.as_store_value()

            assistant_ids = sorted(
                {
                    relation.assistant_id
                    for relation in observation.relations
                    if relation.assistant_id and relation.graph_kind == "agent"
                }
            )
            for assistant_id in assistant_ids:
                path = f"assistants/{quote(assistant_id, safe='')}/graph.json"
                await capture(path, lambda value=assistant_id: client.assistants.get_graph(value))

            if isinstance(configuration, LifecycleConfigurationSnapshot):
                workflow_ids = sorted(
                    {
                        relation.resource_id
                        for relation in observation.relations
                        if relation.graph_kind == "workflow"
                    }
                )
                for workflow_id in workflow_ids:
                    path = f"workflows/{quote(workflow_id, safe='')}/graph.json"

                    async def workflow_document(value: str = workflow_id) -> dict[str, Any]:
                        return self._workflow_document(configuration, value)

                    await capture(path, workflow_document)

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
            lifecycle = await self._lifecycle_record(client, lifecycle_id)
            if lifecycle is None:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle, threads)
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
        record_namespace = list(lifecycle_record_namespace(lifecycle_id))
        for namespace in sorted(
            namespaces,
            key=lambda value: value == record_namespace,
        ):
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
            lifecycle = await self._lifecycle_record(client, lifecycle_id)
            if lifecycle is None:
                raise LangGraphLifecycleNotFound(lifecycle_id)
            threads = await self._threads(client, lifecycle_id)
            observation = await self._observe_lifecycle(client, lifecycle, threads)
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
