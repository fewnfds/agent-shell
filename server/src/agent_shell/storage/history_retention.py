from __future__ import annotations

from agent_shell.storage.file_config import FileConfigRepository


DEFAULT_HISTORY_RETENTION_LIMIT = 20
HISTORY_TYPES = frozenset(
    {"runtime_diagnostics"}
)


class HistoryRetentionStore:
    """Persist retention limits in system.yaml."""

    def __init__(self, repository: FileConfigRepository) -> None:
        self._repository = repository

    @staticmethod
    def _type(history_type: str) -> str:
        if history_type not in HISTORY_TYPES:
            raise ValueError(f"unsupported history type: {history_type}")
        return history_type

    def get_limit(self, history_type: str) -> int:
        history_type = self._type(history_type)
        value = self._repository.system().get("history_retention", {}).get(history_type)
        if value is None:
            raise RuntimeError(f"history retention setting is unavailable: {history_type}")
        return int(value)

    def get_limit_in(self, _connection, history_type: str) -> int:
        history_type = self._type(history_type)
        return self.get_limit(history_type)

    def set_limit_in(self, _connection, history_type: str, retention_limit: int) -> None:
        history_type = self._type(history_type)
        if retention_limit < 1:
            raise ValueError("history retention limit is out of range")
        self._repository.update_system(lambda system: system.setdefault("history_retention", {}).__setitem__(history_type, retention_limit))

    def set_limit(self, history_type: str, retention_limit: int) -> int:
        self.set_limit_in(None, history_type, retention_limit)
        return retention_limit
