from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def _no_op() -> None:
    return None


@dataclass(slots=True)
class StagedPathChange:
    """One owned filesystem change that can be rolled back until commit."""

    rollback_callback: Callable[[], None]
    finalize_callback: Callable[[], None] = _no_op

    def rollback(self) -> None:
        self.rollback_callback()

    def finalize(self) -> None:
        self.finalize_callback()


__all__ = ["StagedPathChange"]
