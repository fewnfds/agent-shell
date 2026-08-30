from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class MediaContentBlock:
    """A completed LangChain content block awaiting media persistence."""

    message_id: str
    block_index: int
    content: dict[str, object]
    stream_id: str = ""


__all__ = ["MediaContentBlock"]
