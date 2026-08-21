from __future__ import annotations

from copy import deepcopy

from agent_shell.security_events import SecurityEventLogger, emit_configuration_events
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.workflow.contracts import (
    WorkflowGraphDefinitionV1,
    WorkflowGraphDocumentV1,
    WorkflowLayoutV1,
)
from agent_shell.workflow_contracts import WorkflowRole


class WorkflowStore:
    def __init__(self, repository: FileConfigRepository, event_logger: SecurityEventLogger | None = None) -> None:
        self._repository = repository
        self._events = event_logger

    @staticmethod
    def _public(record: dict) -> dict:
        return {
            "id": str(record["id"]),
            "name": str(record["name"]),
            "workflow_role": str(record["workflow_role"]),
            "description": str(record["description"]),
            "workflow_event_output_id": record.get("workflow_event_output_id"),
            "recursion_limit": int(record["recursion_limit"]),
            "execution_timeout_seconds": int(record["execution_timeout_seconds"]),
            "max_concurrency": int(record.get("max_concurrency", 100)),
            "enabled": bool(record["enabled"]),
        }

    def list_items(
        self,
        *,
        enabled_only: bool = False,
        workflow_role: WorkflowRole | None = None,
    ) -> list[dict]:
        records = [self._public(item) for item in self._repository.config().get("workflows", [])]
        if enabled_only:
            records = [item for item in records if item["enabled"]]
        if workflow_role is not None:
            records = [item for item in records if item["workflow_role"] == workflow_role]
        return sorted(records, key=lambda value: (value["name"].casefold(), value["id"]))

    def get_item(self, item_id: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            if item.get("id") == item_id:
                return self._public(item)
        return None

    def get_item_by_name(self, name: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            if item.get("name") == name:
                return self._public(item)
        return None

    def get_item_by_event_output(self, component_id: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            if item.get("workflow_event_output_id") == component_id:
                return self._public(item)
        return None

    def get_item_by_command(self, component_id: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            definition = item.get("definition")
            nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict) or node.get("type") != "command":
                    continue
                node_config = node.get("config")
                if (
                    isinstance(node_config, dict)
                    and node_config.get("command_id") == component_id
                ):
                    return self._public(item)
        return None

    def get_item_by_task_dispatcher(self, component_id: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            definition = item.get("definition")
            nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict) or node.get("type") != "task-dispatcher":
                    continue
                node_config = node.get("config")
                if (
                    isinstance(node_config, dict)
                    and node_config.get("task_dispatcher_id") == component_id
                ):
                    return self._public(item)
        return None

    def get_item_by_main_agent(self, main_agent_id: str) -> dict | None:
        for item in self._repository.config().get("workflows", []):
            definition = item.get("definition")
            nodes = definition.get("nodes", []) if isinstance(definition, dict) else []
            for node in nodes if isinstance(nodes, list) else []:
                if not isinstance(node, dict):
                    continue
                node_config = node.get("config")
                if (
                    isinstance(node_config, dict)
                    and node_config.get("main_agent_id") == main_agent_id
                ):
                    return self._public(item)
        return None

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

    def get_graph(self, item_id: str) -> WorkflowGraphDocumentV1 | None:
        for item in self._repository.config().get("workflows", []):
            if item.get("id") == item_id:
                return WorkflowGraphDocumentV1.model_validate({"definition": item.get("definition", {}), "layout": item.get("layout", {})})
        return None

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
