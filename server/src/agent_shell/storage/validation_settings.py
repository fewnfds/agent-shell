from __future__ import annotations

from agent_shell.storage.file_config import FileConfigRepository


MIN_VALIDATION_DEBOUNCE_MS = 100


class ConfigurationValidationSettingsStore:
    def __init__(self, repository: FileConfigRepository) -> None:
        self._repository = repository

    @staticmethod
    def _validated_value(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("configuration validation debounce must be an integer")
        if value < MIN_VALIDATION_DEBOUNCE_MS:
            raise ValueError("configuration validation debounce is out of range")
        return value

    def snapshot(self) -> dict[str, int]:
        value = self._validated_value(
            self._repository.system()
            .get("configuration_validation", {})
            .get("debounce_ms", 1000)
        )
        return self._response(value)

    def update(self, debounce_ms: int) -> dict[str, int]:
        debounce_ms = self._validated_value(debounce_ms)
        self._repository.update_system(
            lambda system: system.setdefault("configuration_validation", {}).__setitem__(
                "debounce_ms", debounce_ms
            )
        )
        return self._response(debounce_ms)

    @staticmethod
    def _response(debounce_ms: int) -> dict[str, int]:
        return {"debounce_ms": debounce_ms, "min_debounce_ms": MIN_VALIDATION_DEBOUNCE_MS}
