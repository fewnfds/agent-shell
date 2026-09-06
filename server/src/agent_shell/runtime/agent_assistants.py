from __future__ import annotations

from uuid import UUID, uuid5


_MAIN_AGENT_ASSISTANT_NAMESPACE = UUID("3c2c55d1-d959-4e80-a767-e861806ef56f")


def main_agent_assistant_id(main_agent_id: str) -> str:
    """Return the stable Agent Server Assistant identity for a Main Agent."""

    canonical_id = str(UUID(main_agent_id))
    return str(uuid5(_MAIN_AGENT_ASSISTANT_NAMESPACE, canonical_id))


__all__ = ["main_agent_assistant_id"]
