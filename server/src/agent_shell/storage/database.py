from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from agent_shell.storage.permissions import secure_database_files, secure_directory
from agent_shell.storage.schema import SCHEMA_SQL


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
    """Own the Agent Shell relational schema and its SQLite transactions."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        with self.transaction() as connection:
            connection.executescript(SCHEMA_SQL)
        self.file_permissions = secure_database_files(self.path)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                yield connection
        finally:
            connection.close()
