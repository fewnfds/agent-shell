from __future__ import annotations

import sqlite3

from agent_shell.storage.database import SQLiteDatabase


class RuntimeManagedDirectoryStore:
    """Own verified references to Shell-created Lifecycle directories."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def register(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_managed_directories ("
                "lifecycle_id, filesystem_id, virtual_path, configured_root, "
                "resolved_target, created_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(lifecycle_id, filesystem_id, virtual_path) DO NOTHING",
                (
                    record["lifecycle_id"],
                    record["filesystem_id"],
                    record["virtual_path"],
                    record["configured_root"],
                    record["resolved_target"],
                    record["created_at"],
                ),
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "lifecycle_id": str(row["lifecycle_id"]),
            "filesystem_id": str(row["filesystem_id"]),
            "virtual_path": str(row["virtual_path"]),
            "configured_root": str(row["configured_root"]),
            "resolved_target": str(row["resolved_target"]),
            "created_at": str(row["created_at"]),
            "released_at": row["released_at"],
        }

    def list_for_lifecycle(self, lifecycle_id: str) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_managed_directories "
                "WHERE lifecycle_id = ? ORDER BY filesystem_id, virtual_path",
                (lifecycle_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def mark_released(
        self,
        lifecycle_id: str,
        filesystem_id: str,
        virtual_path: str,
        *,
        released_at: str,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE runtime_managed_directories SET released_at = ? "
                "WHERE lifecycle_id = ? AND filesystem_id = ? AND virtual_path = ?",
                (released_at, lifecycle_id, filesystem_id, virtual_path),
            )


__all__ = ["RuntimeManagedDirectoryStore"]
