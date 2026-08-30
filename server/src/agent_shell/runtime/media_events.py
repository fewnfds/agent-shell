from __future__ import annotations

from dataclasses import dataclass

from agent_shell.workflow.events import WorkflowEventSourceV1


@dataclass(frozen=True, slots=True)
class MediaContentBlock:
    """A completed LangChain content block awaiting media persistence."""

    timestamp: str
    namespace: str
    agent_name: str
    node: str
    message_id: str
    block_index: int
    content: dict[str, object]
    stream_id: str = ""
    source: WorkflowEventSourceV1 | None = None


__all__ = ["MediaContentBlock"]
