from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Any, Generic, TypeVar

from agent_shell.storage.permissions import secure_database_files, secure_directory
from agent_shell.storage.schema import SCHEMA_SQL


_BatchItem = TypeVar("_BatchItem")
_Result = TypeVar("_Result")


class SQLiteBatchWriter(Generic[_BatchItem]):
    """Buffer one ordered fact stream and persist naturally formed batches."""

    def __init__(
        self,
        database: SQLiteDatabase,
        write_batch: Callable[[tuple[_BatchItem, ...]], None],
        *,
        name: str,
    ) -> None:
        self._database = database
        self._write_batch = write_batch
        self._loop = asyncio.get_running_loop()
        self._pending: deque[_BatchItem] = deque()
        self._wakeup = asyncio.Event()
        self._closing = False
        self._failure: Exception | None = None
        self._task = self._loop.create_task(self._run(), name=name)

    @property
    def failure(self) -> Exception | None:
        return self._failure

    def _require_owner_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("SQLiteBatchWriter belongs to a different event loop")

    def submit(self, item: _BatchItem) -> None:
        """Accept an item without waiting for SQLite or creating a per-item task."""

        self._require_owner_loop()
        if self._failure is not None:
            raise self._failure
        if self._closing:
            raise RuntimeError("SQLiteBatchWriter is closed")
        self._pending.append(item)
        self._wakeup.set()

    async def _run(self) -> None:
        try:
            while True:
                await self._wakeup.wait()
                self._wakeup.clear()
                if self._pending:
                    batch = tuple(self._pending)
                    self._pending.clear()
                    await self._database.run(
                        lambda batch=batch: self._write_batch(batch)
                    )
                if self._closing and not self._pending:
                    return
                if self._pending:
                    self._wakeup.set()
        except Exception as exc:
            self._failure = exc
            self._pending.clear()

    async def close(self) -> None:
        """Stop accepting items, drain accepted work, and surface write failure."""

        self._require_owner_loop()
        self._closing = True
        self._wakeup.set()
        cancelled: asyncio.CancelledError | None = None
        try:
            while not self._task.done():
                try:
                    await asyncio.shield(self._task)
                except asyncio.CancelledError as exc:
                    # Once close begins, accepted facts must finish draining even
                    # when the caller is itself being cancelled.
                    cancelled = exc
            self._task.result()
        finally:
            if self._task.done():
                self._database._release_batch_writer(self)
        if self._failure is not None:
            raise self._failure
        if cancelled is not None:
            raise cancelled


class SQLiteFile:
    """Prepare one SQLite file for a single higher-level persistence owner."""

    def __init__(self, path: Path, *, create: bool = True) -> None:
        self.path = path
        self.directory_permission = secure_directory(self.path.parent)
        self.file_permissions = self.prepare() if create else self._existing_permissions()

    def _existing_permissions(self):
        return secure_database_files(self.path) if self.path.exists() else ()

    def prepare(self):
        if not self.path.exists():
            self.path.touch()
        self.file_permissions = secure_database_files(self.path)
        return self.file_permissions


class SQLiteDatabase(SQLiteFile):
    """Own application SQLite transactions and asynchronous execution."""

    def __init__(self, path: Path) -> None:
        self._transaction_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._batch_writers: set[SQLiteBatchWriter[Any]] = set()
        self._closing = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None
        super().__init__(path)
        with self.transaction() as connection:
            connection.executescript(SCHEMA_SQL)
        self.file_permissions = secure_database_files(self.path)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("SQLiteDatabase is closed")

    def _submit(self, call: Callable[[], _Result]) -> Future[_Result]:
        with self._state_lock:
            self._require_open()
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="agent-shell-sqlite",
                )
            return self._executor.submit(call)

    async def run(self, call: Callable[[], _Result]) -> _Result:
        """Run blocking application-database work off the caller's event loop."""

        return await asyncio.wrap_future(self._submit(call))

    def batch_writer(
        self,
        write_batch: Callable[[tuple[_BatchItem, ...]], None],
        *,
        name: str,
    ) -> SQLiteBatchWriter[_BatchItem]:
        """Create a tracked ordered writer backed by the shared DB executor."""

        with self._state_lock:
            self._require_open()
            if self._closing:
                raise RuntimeError("SQLiteDatabase is closing")
            writer = SQLiteBatchWriter(self, write_batch, name=name)
            self._batch_writers.add(writer)
        return writer

    def _release_batch_writer(self, writer: SQLiteBatchWriter[Any]) -> None:
        with self._state_lock:
            self._batch_writers.discard(writer)

    async def _close(self) -> None:
        with self._state_lock:
            writers = tuple(self._batch_writers)
        results = await asyncio.gather(
            *(writer.close() for writer in writers),
            return_exceptions=True,
        )
        with self._state_lock:
            executor = self._executor
            self._executor = None
            self._closed = True
        if executor is not None:
            await asyncio.to_thread(executor.shutdown, wait=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise BaseExceptionGroup(
                "one or more SQLite batch writers failed while closing",
                failures,
            )

    async def close(self) -> None:
        """Drain tracked batch writers and close the asynchronous executor."""

        loop = asyncio.get_running_loop()
        with self._state_lock:
            task = self._close_task
            if task is None:
                if self._closed:
                    return
                self._closing = True
                task = loop.create_task(self._close(), name="close-application-sqlite")
                self._close_task = task
            elif not task.done() and task.get_loop() is not loop:
                raise RuntimeError("SQLiteDatabase close belongs to another event loop")
        cancelled: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancelled = exc
        task.result()
        if cancelled is not None:
            raise cancelled

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._transaction_lock:
            with self._state_lock:
                self._require_open()
            connection = sqlite3.connect(self.path)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA secure_delete = ON")
                with connection:
                    yield connection
            finally:
                connection.close()
