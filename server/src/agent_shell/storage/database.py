from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from agent_shell.storage.permissions import secure_database_files, secure_directory
from agent_shell.storage.schema import SCHEMA_SQL


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.directory_permission = secure_directory(self.path.parent)
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
