from __future__ import annotations


class ToolCallRegistry:
    """Hold the minimal name state needed to join tool call/result events."""

    def __init__(self) -> None:
        self._names: dict[tuple[str, str, str], str] = {}

    def remember(self, key: tuple[str, str, str], name: str) -> None:
        if name:
            self._names[key] = name

    def get(self, key: tuple[str, str, str]) -> str:
        return self._names.get(key, "")

    def pop(self, key: tuple[str, str, str]) -> str:
        return self._names.pop(key, "")

    def clear(self) -> None:
        self._names.clear()


__all__ = ["ToolCallRegistry"]
