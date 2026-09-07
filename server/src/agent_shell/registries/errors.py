from __future__ import annotations

from collections.abc import Mapping

from agent_shell.localization import (
    MessageArg,
    normalize_message_args,
    normalize_message_key,
)
class ResourceScanError(ValueError):
    def __init__(
        self,
        message_key: str,
        fallback: str,
        message_args: Mapping[str, MessageArg] | None = None,
    ) -> None:
        self.message_key = normalize_message_key(message_key)
        self.message_args = normalize_message_args(message_args)
        super().__init__(fallback)

    def as_dict(self) -> dict[str, object]:
        return {
            "message_key": self.message_key,
            "message_args": dict(self.message_args),
        }
