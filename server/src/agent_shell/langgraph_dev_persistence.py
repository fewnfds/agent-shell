"""Version-scoped LangGraph Dev persistence customization.

Private integration points and upgrade checks: docs/langgraph-dev-customizations.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
import logging
import os
from pathlib import Path
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.storage.atomic_files import write_bytes_atomic


logger = logging.getLogger(__name__)
_VERIFIED_VERSIONS = {
    "langgraph-runtime-inmem": "0.34.3",
    "langgraph-checkpoint": "4.3.0",
}


class LangGraphPersistenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Event.wait raises OverflowError above the platform's CPython timeout bound.
    flush_interval_seconds: int = Field(
        default=10, strict=True, ge=1, le=int(threading.TIMEOUT_MAX)
    )
    write_if_changed: bool = Field(default=True, strict=True)


class _SnapshotWriter:
    def __init__(self, store: Any, policy: LangGraphPersistenceSettings) -> None:
        self._store = store
        self._policy = policy
        self._last_digest: bytes | None = None
        self._lock = threading.Lock()

    def sync(self) -> None:
        # Only sync/shutdown writers share this lock; official in-memory mutations
        # and serialization semantics continue to belong to the runtime.
        with self._lock:
            if self._store.flag == "r":
                return
            with BytesIO() as buffer:
                self._store.dump(buffer)
                content = buffer.getvalue()
            digest = sha256(content).digest() if self._policy.write_if_changed else None
            if digest is not None and digest == self._last_digest:
                return
            write_bytes_atomic(
                Path(self._store.filename), content, skip_if_unchanged=False
            )
            if self._store.mode is not None:
                os.chmod(self._store.filename, self._store.mode)
            # A failed serialization/replace must remain eligible for the next flush.
            self._last_digest = digest


@contextmanager
def configured_dev_persistence(policy: LangGraphPersistenceSettings) -> Iterator[None]:
    """Adapt the official Core resource/retry stores before the dev pool starts."""

    for package, expected in _VERIFIED_VERSIONS.items():
        installed = version(package)
        if installed != expected:
            raise RuntimeError(
                f"LangGraph Dev persistence adaptation requires {package}=={expected}; "
                f"found {installed}. Review docs/langgraph-dev-customizations.md "
                "before updating the verified versions."
            )

    from langgraph_runtime_inmem import _persistence, database

    # Importing the runtime registers its fallback in-memory Store and starts a
    # flush thread. Stop it before adapting; start_pool's Core resource
    # registration will start the configured loop during normal CLI startup.
    _persistence.stop_flush_loop()
    stores = (database.GLOBAL_STORE, database.GLOBAL_RETRY_COUNTER._counters)

    def flush_loop(stop_event: threading.Event) -> None:
        while not stop_event.wait(timeout=_persistence._flush_interval):
            for filename, reference in list(_persistence._stores.items()):
                store = reference()
                if store is None:
                    if _persistence._stores.get(filename) is reference:
                        _persistence._stores.pop(filename, None)
                    continue
                # Keep the upstream behavior for unrelated empty fallback stores,
                # while still persisting deletion/clear of the adapted stores.
                if not store and not any(store is adapted for adapted in stores):
                    continue
                try:
                    store.sync()
                except Exception:
                    logger.exception(
                        "LangGraph Dev persistence failed for %s; retrying next interval",
                        filename,
                    )

    original_interval = _persistence._flush_interval
    original_loop = _persistence._flush_loop
    original_syncs = [store.__dict__.get("sync") for store in stores]
    try:
        _persistence._flush_interval = policy.flush_interval_seconds
        _persistence._flush_loop = flush_loop
        for store in stores:
            store.sync = _SnapshotWriter(store, policy).sync
        yield
    finally:
        # The CLI normally stops its pool during lifespan shutdown. Also stop a
        # partially started loop before restoring methods after a startup error.
        _persistence.stop_flush_loop()
        for store, original in zip(stores, original_syncs, strict=True):
            if original is None:
                del store.sync
            else:
                store.sync = original
        _persistence._flush_loop = original_loop
        _persistence._flush_interval = original_interval
