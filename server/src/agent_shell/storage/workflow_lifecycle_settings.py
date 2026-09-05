from __future__ import annotations

from typing import Any

from agent_shell.storage.file_config import FileConfigRepository


DEFAULT_RETAINED_LIFECYCLES = 20
MIN_RETAINED_LIFECYCLES = 0


class WorkflowLifecycleSettingsStore:
    """Persist settings owned by Workflow Lifecycle monitoring."""

    _section = "workflow_lifecycles"

    def __init__(self, repository: FileConfigRepository) -> None:
        self._repository = repository

    @staticmethod
    def _retained_lifecycles(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retained_lifecycles must be an integer")
        if value < MIN_RETAINED_LIFECYCLES:
            raise ValueError(
                f"retained_lifecycles must be at least {MIN_RETAINED_LIFECYCLES}"
            )
        return value

    def snapshot(self) -> dict[str, int]:
        section = self._repository.system().get(self._section, {})
        value = (
            section.get("retained_lifecycles", DEFAULT_RETAINED_LIFECYCLES)
            if isinstance(section, dict)
            else DEFAULT_RETAINED_LIFECYCLES
        )
        return {"retained_lifecycles": self._retained_lifecycles(value)}

    def public(self) -> dict[str, Any]:
        return {
            **self.snapshot(),
            "defaults": {"retained_lifecycles": DEFAULT_RETAINED_LIFECYCLES},
            "minimums": {"retained_lifecycles": MIN_RETAINED_LIFECYCLES},
            "configurable": True,
        }

    def update(self, retained_lifecycles: int) -> dict[str, Any]:
        value = self._retained_lifecycles(retained_lifecycles)
        self._repository.update_system(
            lambda system: system.setdefault(self._section, {}).__setitem__(
                "retained_lifecycles", value
            )
        )
        return self.public()


__all__ = [
    "DEFAULT_RETAINED_LIFECYCLES",
    "MIN_RETAINED_LIFECYCLES",
    "WorkflowLifecycleSettingsStore",
]
