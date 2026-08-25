from __future__ import annotations

import sqlite3

from agent_shell.storage.database import SQLiteDatabase


class WorkflowLifecycleStore:
    """Persist the queryable management index for Workflow Lifecycles."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, object]:
        record: dict[str, object] = {
            "lifecycle_id": row["lifecycle_id"],
            "request_id": row["request_id"],
            "parent_run_id": row["parent_run_id"],
            "workflow_id": row["workflow_id"],
            "workflow_name": row["workflow_name"],
            "created_at": row["created_at"],
            "lifecycle_status": row["lifecycle_status"],
            "parent_status": row["parent_status"],
            "messages_sha": row["messages_sha"],
            "message_count": row["message_count"],
        }
        if row["parent_finished_at"] is not None:
            record["parent_finished_at"] = row["parent_finished_at"]
        if row["deletion_started_at"] is not None:
            record["deletion_started_at"] = row["deletion_started_at"]
        return record

    def create(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO workflow_lifecycles "
                "(lifecycle_id, request_id, parent_run_id, workflow_id, "
                "workflow_name, created_at, lifecycle_status, "
                "parent_status, parent_finished_at, deletion_started_at, "
                "messages_sha, message_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                (
                    record["lifecycle_id"],
                    record["request_id"],
                    record["parent_run_id"],
                    record["workflow_id"],
                    record["workflow_name"],
                    record["created_at"],
                    record["lifecycle_status"],
                    record["parent_status"],
                    record["messages_sha"],
                    record["message_count"],
                ),
            )

    def get(self, lifecycle_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_lifecycles WHERE lifecycle_id = ?",
                (lifecycle_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    @staticmethod
    def _query_clause(query: str) -> tuple[str, tuple[object, ...]]:
        normalized_query = query.strip()
        if not normalized_query:
            return "", ()
        return (
            "WHERE instr(lower(workflow_name), lower(?)) > 0 "
            "OR instr(lower(workflow_id), lower(?)) > 0 "
            "OR instr(lower(lifecycle_id), lower(?)) > 0 "
            "OR instr(lower(request_id), lower(?)) > 0",
            (normalized_query,) * 4,
        )

    def list_page(
        self,
        *,
        limit: int,
        offset: int,
        query: str = "",
    ) -> tuple[list[dict[str, object]], int]:
        where, parameters = self._query_clause(query)
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM workflow_lifecycles {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM workflow_lifecycles {where} "
                "ORDER BY created_at DESC, lifecycle_id DESC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._row(row) for row in rows], total

    def list_matching_ids(self, *, query: str = "") -> list[str]:
        where, parameters = self._query_clause(query)
        with self._database.transaction() as connection:
            rows = connection.execute(
                f"SELECT lifecycle_id FROM workflow_lifecycles {where} "
                "ORDER BY created_at DESC, lifecycle_id DESC",
                parameters,
            ).fetchall()
        return [str(row["lifecycle_id"]) for row in rows]

    def finish_parent(
        self,
        lifecycle_id: str,
        *,
        status: str,
        finished_at: str,
    ) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_lifecycles "
                "SET parent_status = ?, parent_finished_at = ? "
                "WHERE lifecycle_id = ?",
                (status, finished_at, lifecycle_id),
            )
        return cursor.rowcount > 0

    def cancel_running(self, *, finished_at: str) -> int:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_lifecycles "
                "SET parent_status = 'cancelled', parent_finished_at = ? "
                "WHERE parent_status = 'running'",
                (finished_at,),
            )
        return cursor.rowcount

    def mark_deleting(self, lifecycle_id: str, *, started_at: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_lifecycles "
                "SET lifecycle_status = 'deleting', deletion_started_at = ? "
                "WHERE lifecycle_id = ?",
                (started_at, lifecycle_id),
            )
        return cursor.rowcount > 0

    def delete(self, lifecycle_id: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM workflow_lifecycles WHERE lifecycle_id = ?",
                (lifecycle_id,),
            )
        return cursor.rowcount > 0


__all__ = ["WorkflowLifecycleStore"]
