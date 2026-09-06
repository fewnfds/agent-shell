from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FramePhase = Literal["start", "delta", "finish", "atomic", "abort"]


@dataclass(frozen=True, slots=True)
class PresentationFrame:
    """Projected public text with provider-neutral presentation boundaries.

    ``block_id`` identifies one official text/reasoning content block.
    ``segment_end_text`` is an optional opaque suffix used when a scheduler
    must temporarily close that block during an idle handoff.
    """

    phase: FramePhase
    text: str
    block_id: str = ""
    segment_end_text: str = ""
    continuation: bool = False
    close_reason: str = ""
    sequence: int = 0


__all__ = ["FramePhase", "PresentationFrame"]
