from __future__ import annotations

from copy import deepcopy

from agent_shell.security_events import SecurityEventLogger, emit_configuration_events
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.workflow.contracts import (
    WorkflowGraphDefinitionV1,
    WorkflowGraphDocumentV1,
    WorkflowLayoutV1,
)
class WorkflowStore:
    _PUBLIC_FIELDS = (
        "id",
        "name",
        "description",
        "is_model_entry",
        "workflow_event_output_id",
        "durability",
        "on_disconnect",
        "enabled",
    )

    def __init__(self, repository: FileConfigRepository, event_logger: SecurityEventLogger | None = None) -> None:
        self._repository = repository
        self._events = event_logger

    @staticmethod
    def _public(record: dict) -> dict:
        public = {
            "id": str(record["id"]),
            "name": str(record["name"]),
            "description": str(record["description"]),
            "is_model_entry": bool(record.get("is_model_entry", False)),
            "workflow_event_output_id": record.get("workflow_event_output_id"),
            "durability": str(record.get("durability", "async")),
            "on_disconnect": str(record.get("on_disconnect", "cancel")),
            "enabled": bool(record["enabled"]),
        }
        return public

    def list_items(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[dict]:
        records = [
            self._public(item)
            for item in self._repository.list_records(
                "workflows", fields=self._PUBLIC_FIELDS
            )
        ]
        if enabled_only:
            records = [item for item in records if item["enabled"]]
        return sorted(records, key=lambda value: (value["name"].casefold(), value["id"]))

    def list_item_summaries(
        self,
    ) -> list[dict]:
        fields = ("id", "name", "description", "enabled")
        records = self._repository.list_records("workflows", fields=fields)
        return sorted(
            records,
            key=lambda value: (
                str(value.get("name", "")).casefold(),
                str(value.get("id", "")),
            ),
        )

    def get_item(self, item_id: str) -> dict | None:
        item = self._repository.get_record(
            "workflows", item_id, fields=self._PUBLIC_FIELDS
        )
        return self._public(item) if item is not None else None

    def get_item_by_name(self, name: str) -> dict | None:
        item = self._repository.find_record(
            "workflows", "name", name, fields=self._PUBLIC_FIELDS
        )
        return self._public(item) if item is not None else None

    def save_item(
        self,
        item_id: str,
        data: dict,
        *,
        expected_repository_id: str | None = None,
    ) -> None:
        existing = self.get_item(item_id)
        empty_definition = WorkflowGraphDefinitionV1().model_dump(mode="json")
        empty_layout = WorkflowLayoutV1().model_dump(mode="json")

        def mutate(config: dict) -> None:
            records = config.setdefault("workflows", [])
            if any(
                item.get("name") == data["name"] and item.get("id") != item_id
                for item in records
            ):
                raise ValueError("workflow name already exists")
            stored = deepcopy(data)
            stored["id"] = item_id
            stored.setdefault("definition", deepcopy(empty_definition))
            stored.setdefault("layout", deepcopy(empty_layout))
            for index, item in enumerate(records):
                if item.get("id") == item_id:
                    stored["definition"] = deepcopy(item.get("definition", empty_definition))
                    stored["layout"] = deepcopy(item.get("layout", empty_layout))
                    records[index] = stored
                    break
            else:
                records.append(stored)

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        emit_configuration_events(self._events, action="updated" if existing else "created", entity="workflow", entity_id=item_id)

    def copy_item(
        self,
        source_id: str,
        item_id: str,
        data: dict,
        *,
        expected_repository_id: str | None = None,
    ) -> bool:
        copied = False
        empty_definition = WorkflowGraphDefinitionV1().model_dump(mode="json")
        empty_layout = WorkflowLayoutV1().model_dump(mode="json")

        def mutate(config: dict) -> None:
            nonlocal copied
            records = config.setdefault("workflows", [])
            source = next(
                (item for item in records if item.get("id") == source_id),
                None,
            )
            if source is None:
                return
            if any(item.get("name") == data["name"] for item in records):
                raise ValueError("workflow name already exists")
            stored = deepcopy(data)
            stored["id"] = item_id
            stored["enabled"] = False
            stored["definition"] = deepcopy(
                source.get("definition", empty_definition)
            )
            stored["layout"] = deepcopy(source.get("layout", empty_layout))
            records.append(stored)
            copied = True

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        if copied:
            emit_configuration_events(
                self._events,
                action="created",
                entity="workflow",
                entity_id=item_id,
            )
        return copied

    def get_graph(self, item_id: str) -> WorkflowGraphDocumentV1 | None:
        item = self._repository.get_record(
            "workflows", item_id, fields=("definition", "layout")
        )
        if item is None:
            return None
        return WorkflowGraphDocumentV1.model_validate(
            {
                "definition": item.get("definition", {}),
                "layout": item.get("layout", {}),
            }
        )

    def save_graph_and_enabled(
        self,
        item_id: str,
        document: WorkflowGraphDocumentV1,
        *,
        enabled: bool,
        expected_repository_id: str | None = None,
    ) -> bool:
        changed = False

        def mutate(config: dict) -> None:
            nonlocal changed
            for item in config.setdefault("workflows", []):
                if item.get("id") == item_id:
                    item["definition"] = document.definition.model_dump(mode="json")
                    item["layout"] = document.layout.model_dump(mode="json")
                    item["enabled"] = bool(enabled)
                    changed = True
                    break

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        if changed:
            emit_configuration_events(self._events, action="updated", entity="workflow", entity_id=item_id)
        return changed

    def delete_items(
        self,
        item_ids: list[str],
        *,
        expected_repository_id: str | None = None,
    ) -> int:
        unique_ids = set(item_ids)
        if not unique_ids:
            return 0
        removed: list[str] = []

        def mutate(config: dict) -> None:
            records = config.setdefault("workflows", [])
            retained = []
            for item in records:
                if item.get("id") in unique_ids:
                    removed.append(str(item.get("id")))
                else:
                    retained.append(item)
            config["workflows"] = retained

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        for item_id in removed:
            emit_configuration_events(self._events, action="deleted", entity="workflow", entity_id=item_id)
        return len(removed)

    def delete_item(
        self,
        item_id: str,
        *,
        expected_repository_id: str | None = None,
    ) -> bool:
        return self.delete_items(
            [item_id], expected_repository_id=expected_repository_id
        ) == 1

    def new_id(self) -> str:
        return self._repository.new_configuration_id()

    def repository_id(self) -> str:
        return self._repository.repository_id

    def repository_context(self) -> tuple[str, int]:
        return self._repository.repository_context()
