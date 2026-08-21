from __future__ import annotations

from agent_shell.storage.file_config import FileConfigRepository


DEFAULT_SYSTEM_LOG_MAX_SIZE_MIB = 5
MIN_SYSTEM_LOG_MAX_SIZE_MIB = 1
MIB_BYTES = 1024 * 1024


class SystemLogSettingsStore:
    def __init__(self, repository: FileConfigRepository) -> None:
        self._repository = repository

    def snapshot(self) -> dict[str, int]:
        value = int(self._repository.system().get("system_log", {}).get("max_size_mib", DEFAULT_SYSTEM_LOG_MAX_SIZE_MIB))
        return {"max_size_mib": value, "min_size_mib": MIN_SYSTEM_LOG_MAX_SIZE_MIB}

    def set_max_size_mib(self, max_size_mib: int) -> dict[str, int]:
        if max_size_mib < MIN_SYSTEM_LOG_MAX_SIZE_MIB:
            raise ValueError("system log maximum size is out of range")
        self._repository.update_system(lambda system: system.setdefault("system_log", {}).__setitem__("max_size_mib", max_size_mib))
        return {"max_size_mib": max_size_mib, "min_size_mib": MIN_SYSTEM_LOG_MAX_SIZE_MIB}
