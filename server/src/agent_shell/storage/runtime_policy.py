from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from agent_shell.storage.file_config import FileConfigRepository


@dataclass(frozen=True, slots=True)
class RuntimePolicy:
    chat_completion_body_bytes: int = 64 * 1024 * 1024
    content_blocks: int = 4096
    decoded_block_bytes: int = 24 * 1024 * 1024
    decoded_total_bytes: int = 48 * 1024 * 1024
    provider_timeout_seconds: int = 600
    provider_connect_timeout_seconds: int = 5


RUNTIME_POLICY_DEFAULTS = RuntimePolicy()
RUNTIME_POLICY_MINIMUMS = RuntimePolicy(
    chat_completion_body_bytes=1,
    content_blocks=1,
    decoded_block_bytes=1,
    decoded_total_bytes=1,
    provider_timeout_seconds=1,
    provider_connect_timeout_seconds=1,
)


class RuntimePolicyStore:
    """Persist user-controlled resource and transport policy in one owner."""

    _section = "runtime_policy"

    def __init__(self, repository: FileConfigRepository) -> None:
        self._repository = repository

    @staticmethod
    def _validated_value(name: str, value: object) -> int | bool:
        default = getattr(RUNTIME_POLICY_DEFAULTS, name)
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"runtime policy {name} must be a boolean")
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"runtime policy {name} must be an integer")
        minimum = getattr(RUNTIME_POLICY_MINIMUMS, name)
        if value < minimum:
            raise ValueError(f"runtime policy {name} must be at least {minimum}")
        return value

    def snapshot(self) -> RuntimePolicy:
        values = self._repository.system().get(self._section, {})
        if not isinstance(values, dict):
            values = {}
        defaults = asdict(RUNTIME_POLICY_DEFAULTS)
        normalized = {
            name: self._validated_value(name, values.get(name, default))
            for name, default in defaults.items()
        }
        return RuntimePolicy(**normalized)

    def public(self) -> dict[str, Any]:
        current = asdict(self.snapshot())
        return {
            **current,
            "defaults": asdict(RUNTIME_POLICY_DEFAULTS),
            "minimums": asdict(RUNTIME_POLICY_MINIMUMS),
            "configurable": True,
        }

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        names = {item.name for item in fields(RuntimePolicy)}
        current = asdict(self.snapshot())
        candidate: dict[str, int | bool] = {}
        for name in names:
            candidate[name] = self._validated_value(
                name, values.get(name, current[name])
            )

        self._repository.update_system(
            lambda system: system.__setitem__(self._section, candidate)
        )
        return self.public()


__all__ = [
    "RUNTIME_POLICY_DEFAULTS",
    "RUNTIME_POLICY_MINIMUMS",
    "RuntimePolicy",
    "RuntimePolicyStore",
]
