from __future__ import annotations

from copy import deepcopy

from agent_shell.configuration.identity import name_collision_key
from agent_shell.security_events import SecurityEventLogger, emit_configuration_events
from agent_shell.storage.file_config import FileConfigRepository


class AgentConfigStore:
    _IDENTITY_COLUMNS = {"main_agents": "name", "subagents": "component_name"}

    def __init__(self, repository: FileConfigRepository, event_logger: SecurityEventLogger | None = None) -> None:
        self._repository = repository
        self._events = event_logger

    def _table(self, table: str) -> str:
        if table not in self._IDENTITY_COLUMNS:
            raise ValueError(f"unsupported agent config table: {table}")
        return table

    def _identity_column(self, table: str) -> str:
        return self._IDENTITY_COLUMNS[self._table(table)]

    def list_items(self, table: str) -> list[dict]:
        table = self._table(table)
        identity = self._identity_column(table)
        return sorted(
            self._repository.list_records(table),
            key=lambda value: (str(value.get(identity, "")).casefold(), str(value.get("id", ""))),
        )

    def list_item_summaries(self, table: str) -> list[dict]:
        table = self._table(table)
        identity = self._identity_column(table)
        fields = (
            ("id", "name")
            if table == "main_agents"
            else ("id", "component_name", "name", "description")
        )
        return sorted(
            self._repository.list_records(table, fields=fields),
            key=lambda value: (
                str(value.get(identity, "")).casefold(),
                str(value.get("id", "")),
            ),
        )

    def get_item(self, table: str, item_id: str) -> dict | None:
        table = self._table(table)
        return self._repository.get_record(table, item_id)

    def get_item_by_name(self, table: str, name: str) -> dict | None:
        table = self._table(table)
        identity = self._identity_column(table)
        return self._repository.find_record(table, identity, name)

    def save_item(
        self,
        table: str,
        item_id: str,
        data: dict,
        *,
        expected_repository_id: str | None = None,
    ) -> None:
        table = self._table(table)
        identity = self._identity_column(table)
        name = data[identity]
        existing = self.get_item(table, item_id)

        def mutate(config: dict) -> None:
            records = config.setdefault(table, [])
            if any(
                name_collision_key(str(item.get(identity, "")))
                == name_collision_key(name)
                and item.get("id") != item_id
                for item in records
            ):
                raise ValueError(f"名称「{name}」已存在")
            stored = deepcopy(data)
            stored["id"] = item_id
            for index, item in enumerate(records):
                if item.get("id") == item_id:
                    records[index] = stored
                    break
            else:
                records.append(stored)

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        emit_configuration_events(
            self._events,
            action="updated" if existing is not None else "created",
            entity="main-agent" if table == "main_agents" else "subagent",
            entity_id=item_id,
        )

    def delete_items(
        self,
        table: str,
        item_ids: list[str],
        *,
        expected_repository_id: str | None = None,
    ) -> int:
        table = self._table(table)
        unique_ids = list(dict.fromkeys(item_ids))
        if not unique_ids:
            return 0
        removed: list[str] = []

        def mutate(config: dict) -> None:
            records = config.setdefault(table, [])
            retained = []
            for item in records:
                if item.get("id") in unique_ids:
                    removed.append(str(item.get("id")))
                else:
                    retained.append(item)
            config[table] = retained

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        for item_id in removed:
            emit_configuration_events(
                self._events,
                action="deleted",
                entity="main-agent" if table == "main_agents" else "subagent",
                entity_id=item_id,
            )
        return len(removed)

    def delete_item(
        self,
        table: str,
        item_id: str,
        *,
        expected_repository_id: str | None = None,
    ) -> bool:
        return self.delete_items(
            table,
            [item_id],
            expected_repository_id=expected_repository_id,
        ) == 1

    def new_id(self) -> str:
        return self._repository.new_configuration_id()

    def repository_id(self) -> str:
        return self._repository.repository_id

    def repository_context(self) -> tuple[str, int]:
        return self._repository.repository_context()
