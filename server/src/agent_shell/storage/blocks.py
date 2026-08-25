from __future__ import annotations

from copy import deepcopy

from agent_shell.configuration.identity import name_collision_key
from agent_shell.security_events import SecurityEventLogger, emit_configuration_events
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.reference_mutations import detach_component_references


class BlockStore:
    def __init__(
        self,
        repository: FileConfigRepository,
        event_logger: SecurityEventLogger | None = None,
    ) -> None:
        self._repository = repository
        self._events = event_logger

    @staticmethod
    def _records(config: dict, block_type: str) -> list[dict]:
        components = config.setdefault("components", {})
        records = components.setdefault(block_type, [])
        if not isinstance(records, list):
            raise ValueError(f"component section must be a list: {block_type}")
        return records

    def list_blocks(self, block_type: str) -> list[dict]:
        records = sorted(
            self._repository.list_component_records(block_type),
            key=lambda value: (str(value.get("name", "")).casefold(), str(value.get("id", ""))),
        )
        return records

    def list_block_summaries(self, block_type: str) -> list[dict[str, str]]:
        records = self._repository.list_component_records(
            block_type, fields=("id", "name")
        )
        return sorted(
            records,
            key=lambda value: (
                str(value.get("name", "")).casefold(),
                str(value.get("id", "")),
            ),
        )

    def list_blocks_internal(self, block_type: str) -> list[dict]:
        return self._repository.list_component_records(block_type)

    def list_block_headers(self) -> list[dict[str, str]]:
        headers = self._repository.list_component_headers()
        return sorted(headers, key=lambda value: (value["block_type"], value["name"].casefold(), value["id"]))

    def get_block_header(self, block_id: str) -> dict[str, str] | None:
        return self._repository.get_component_header(block_id)

    def get_block(self, block_type: str, block_id: str) -> dict | None:
        return self._repository.get_component_record(block_type, block_id)

    def get_block_internal(self, block_type: str, block_id: str) -> dict | None:
        return self._repository.get_component_record(block_type, block_id)

    def save_block(
        self,
        block_type: str,
        block_id: str,
        data: dict,
        *,
        expected_repository_id: str | None = None,
    ) -> None:
        name = data["name"]
        existing: dict | None = None
        def mutate(config: dict) -> None:
            nonlocal existing
            records = self._records(config, block_type)
            for record in records:
                if record.get("id") == block_id:
                    existing = deepcopy(record)
                if (
                    name_collision_key(str(record.get("name", "")))
                    == name_collision_key(name)
                    and record.get("id") != block_id
                ):
                    raise ValueError(f"名称「{name}」已存在")
            stored = {key: deepcopy(value) for key, value in data.items() if key != "name"}
            stored["id"] = block_id
            stored["name"] = name
            replaced = False
            for index, record in enumerate(records):
                if record.get("id") == block_id:
                    records[index] = stored
                    replaced = True
                    break
            if not replaced:
                records.append(stored)

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        emit_configuration_events(
            self._events,
            action="updated" if existing is not None else "created",
            entity="block",
            entity_id=block_id,
            capability_type=block_type,
        )

    def copy_block(
        self,
        block_type: str,
        source_id: str,
        new_id: str,
        name: str,
        *,
        source: dict | None = None,
        expected_repository_id: str | None = None,
    ) -> dict | None:
        source_record = source or self.get_block_internal(block_type, source_id)
        if source_record is None:
            return None
        if any(
            name_collision_key(str(item.get("name", "")))
            == name_collision_key(name)
            for item in self.list_blocks_internal(block_type)
        ):
            raise ValueError(f"名称「{name}」已存在")
        copied = deepcopy(source_record)
        copied["id"] = new_id
        copied["name"] = name

        def mutate(config: dict) -> None:
            self._records(config, block_type).append(copied)

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        emit_configuration_events(
            self._events,
            action="copied",
            entity="block",
            entity_id=new_id,
            capability_type=block_type,
        )
        return self.get_block(block_type, new_id)

    def delete_blocks(
        self,
        block_type: str,
        block_ids: list[str],
        *,
        detach_references: bool = False,
        expected_repository_id: str | None = None,
    ) -> int:
        unique_ids = list(dict.fromkeys(block_ids))
        if not unique_ids:
            return 0
        removed: list[dict] = []

        def mutate(config: dict) -> None:
            records = self._records(config, block_type)
            retained: list[dict] = []
            for record in records:
                if record.get("id") in unique_ids:
                    removed.append(deepcopy(record))
                else:
                    retained.append(record)
            config.setdefault("components", {})[block_type] = retained
            if detach_references:
                detach_component_references(config, block_type, set(unique_ids))

        self._repository.update_config(
            mutate, expected_repository_id=expected_repository_id
        )
        for record in removed:
            emit_configuration_events(
                self._events,
                action="deleted",
                entity="block",
                entity_id=str(record.get("id", "")),
                capability_type=block_type,
            )
        return len(removed)

    def delete_block(
        self,
        block_type: str,
        block_id: str,
        *,
        detach_references: bool = False,
        expected_repository_id: str | None = None,
    ) -> bool:
        return self.delete_blocks(
            block_type,
            [block_id],
            detach_references=detach_references,
            expected_repository_id=expected_repository_id,
        ) == 1
    def new_id(self) -> str:
        return self._repository.new_configuration_id()
    def repository_id(self) -> str:
        return self._repository.repository_id

    def repository_context(self) -> tuple[str, int]:
        return self._repository.repository_context()
