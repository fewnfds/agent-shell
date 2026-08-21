from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import threading


class ConfigurationMutationCoordinator:
    """Serialize canonical configuration mutations within one service process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    @contextmanager
    def mutation(self) -> Iterator[None]:
        with self._lock:
            yield


__all__ = ["ConfigurationMutationCoordinator"]
