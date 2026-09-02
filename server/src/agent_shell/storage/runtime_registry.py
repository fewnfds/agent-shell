from __future__ import annotations

from collections import Counter
import sqlite3

from agent_shell.storage.database import SQLiteDatabase


TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted"}
)


class RuntimeRegistryStore:
    """Own required Lifecycle and Workflow Run control facts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, object]:
        return {
            "run_id": str(row["run_id"]),
            "lifecycle_id": str(row["lifecycle_id"]),
            "request_id": str(row["request_id"]),
            "checkpoint_thread_id": row["checkpoint_thread_id"],
            "workflow_id": str(row["workflow_id"]),
            "workflow_name": str(row["workflow_name"]),
            "parent_run_id": row["parent_run_id"],
            "background_task_id": row["background_task_id"],
            "run_depth": int(row["run_depth"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "finish_reason": str(row["finish_reason"]),
            "error_code": str(row["error_code"]),
            "usage": {
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            },
        }

    @staticmethod
    def _lifecycle(row: sqlite3.Row) -> dict[str, object]:
        record: dict[str, object] = {
            "lifecycle_id": str(row["lifecycle_id"]),
            "request_id": str(row["request_id"]),
            "root_run_id": str(row["root_run_id"]),
            "workflow_id": str(row["workflow_id"]),
            "workflow_name": str(row["workflow_name"]),
            "created_at": str(row["created_at"]),
            "lifecycle_status": str(row["lifecycle_status"]),
            "monitoring_capture_enabled": bool(
                row["monitoring_capture_enabled"]
            ),
            "messages_sha": str(row["messages_sha"]),
            "message_count": int(row["message_count"]),
        }
        if "root_status" in row.keys():
            record["root_status"] = str(row["root_status"])
        if row["fully_terminal_at"] is not None:
            record["fully_terminal_at"] = str(row["fully_terminal_at"])
        if row["deletion_started_at"] is not None:
            record["deletion_started_at"] = str(row["deletion_started_at"])
        return record

    @staticmethod
    def _run_values(record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["run_id"],
            record["lifecycle_id"],
            record["request_id"],
            record.get("checkpoint_thread_id") or None,
            record["workflow_id"],
            record["workflow_name"],
            record.get("parent_run_id") or None,
            record.get("background_task_id") or None,
            int(record.get("run_depth", 0)),
            record["created_at"],
        )

    @staticmethod
    def _insert_run(connection: sqlite3.Connection, record: dict[str, object]) -> None:
        connection.execute(
            "INSERT INTO runtime_workflow_runs ("
            "run_id, lifecycle_id, request_id, checkpoint_thread_id, "
            "workflow_id, workflow_name, parent_run_id, background_task_id, "
            "run_depth, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            RuntimeRegistryStore._run_values(record),
        )

    def create_lifecycle(
        self,
        lifecycle: dict[str, object],
        root_run: dict[str, object],
    ) -> None:
        """Atomically create the Lifecycle identity and its required root Run."""

        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_lifecycles ("
                "lifecycle_id, request_id, root_run_id, workflow_id, "
                "workflow_name, created_at, lifecycle_status, "
                "monitoring_capture_enabled, messages_sha, message_count) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (
                    lifecycle["lifecycle_id"],
                    lifecycle["request_id"],
                    lifecycle["root_run_id"],
                    lifecycle["workflow_id"],
                    lifecycle["workflow_name"],
                    lifecycle["created_at"],
                    int(bool(lifecycle["monitoring_capture_enabled"])),
                    lifecycle["messages_sha"],
                    int(lifecycle["message_count"]),
                ),
            )
            self._insert_run(connection, root_run)

    def create_run(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            parent_run_id = str(record.get("parent_run_id") or "")
            if not parent_run_id:
                raise ValueError("a child Workflow Run must have a parent_run_id")
            parent = connection.execute(
                "SELECT lifecycle_id, request_id, run_depth "
                "FROM runtime_workflow_runs WHERE run_id = ?",
                (parent_run_id,),
            ).fetchone()
            if parent is None:
                raise ValueError("the parent Workflow Run does not exist")
            if str(parent["lifecycle_id"]) != str(record["lifecycle_id"]):
                raise ValueError(
                    "a child Workflow Run must share its parent's Lifecycle"
                )
            if str(parent["request_id"]) != str(record["request_id"]):
                raise ValueError(
                    "a child Workflow Run must share its parent's request"
                )
            if int(record.get("run_depth", 0)) != int(parent["run_depth"]) + 1:
                raise ValueError(
                    "a child Workflow Run depth must follow its parent"
                )
            if not str(record.get("background_task_id") or ""):
                raise ValueError(
                    "a child Workflow Run must have a background_task_id"
                )
            self._insert_run(connection, record)

    def get_run(self, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._run(row) if row is not None else None

    def list_runs(self, lifecycle_id: str) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_workflow_runs WHERE lifecycle_id = ? "
                "ORDER BY created_at, run_id",
                (lifecycle_id,),
            ).fetchall()
        return [self._run(row) for row in rows]

    def start_run(self, run_id: str, *, started_at: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_workflow_runs SET status = 'running', "
                "started_at = ? WHERE run_id = ? AND status = 'pending'",
                (started_at, run_id),
            )
        return cursor.rowcount > 0

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: str,
        finish_reason: str,
        error_code: str,
        usage: dict[str, int],
    ) -> bool:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("invalid terminal Workflow Run status")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_workflow_runs SET status = ?, finished_at = ?, "
                "finish_reason = ?, error_code = ?, input_tokens = ?, "
                "output_tokens = ?, total_tokens = ? WHERE run_id = ? "
                "AND status IN ('pending', 'running')",
                (
                    status,
                    finished_at,
                    finish_reason,
                    error_code,
                    int(usage.get("input_tokens", 0)),
                    int(usage.get("output_tokens", 0)),
                    int(usage.get("total_tokens", 0)),
                    run_id,
                ),
            )
        return cursor.rowcount > 0

    def interrupt_active(self, *, finished_at: str) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_workflow_runs "
                "WHERE status IN ('pending', 'running')"
            ).fetchall()
            connection.execute(
                "UPDATE runtime_workflow_runs SET status = 'interrupted', "
                "finished_at = ?, error_code = 'service_restarted' "
                "WHERE status IN ('pending', 'running')",
                (finished_at,),
            )
        interrupted = [self._run(row) for row in rows]
        for record in interrupted:
            record["status"] = "interrupted"
            record["finished_at"] = finished_at
            record["error_code"] = "service_restarted"
        return interrupted

    def get_lifecycle(self, lifecycle_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT lifecycle.*, root.status AS root_status "
                "FROM runtime_lifecycles AS lifecycle "
                "JOIN runtime_workflow_runs AS root "
                "ON root.run_id = lifecycle.root_run_id "
                "WHERE lifecycle.lifecycle_id = ?",
                (lifecycle_id,),
            ).fetchone()
        return self._lifecycle(row) if row is not None else None

    @staticmethod
    def _query_clause(query: str) -> tuple[str, tuple[object, ...]]:
        normalized = query.strip()
        if not normalized:
            return "", ()
        return (
            "WHERE instr(lower(lifecycle.workflow_name), lower(?)) > 0 "
            "OR instr(lower(lifecycle.workflow_id), lower(?)) > 0 "
            "OR instr(lower(lifecycle.lifecycle_id), lower(?)) > 0 "
            "OR instr(lower(lifecycle.request_id), lower(?)) > 0",
            (normalized,) * 4,
        )

    def list_lifecycles(
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
                    "SELECT COUNT(*) FROM runtime_lifecycles AS lifecycle "
                    f"{where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT lifecycle.*, root.status AS root_status "
                "FROM runtime_lifecycles AS lifecycle "
                "JOIN runtime_workflow_runs AS root "
                "ON root.run_id = lifecycle.root_run_id "
                f"{where} ORDER BY lifecycle.created_at DESC, "
                "lifecycle.lifecycle_id DESC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._lifecycle(row) for row in rows], total

    def list_matching_ids(self, *, query: str = "") -> list[str]:
        where, parameters = self._query_clause(query)
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT lifecycle.lifecycle_id "
                "FROM runtime_lifecycles AS lifecycle "
                f"{where} ORDER BY lifecycle.created_at DESC, "
                "lifecycle.lifecycle_id DESC",
                parameters,
            ).fetchall()
        return [str(row["lifecycle_id"]) for row in rows]

    def list_all_lifecycles(self) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT lifecycle.*, root.status AS root_status "
                "FROM runtime_lifecycles AS lifecycle "
                "JOIN runtime_workflow_runs AS root "
                "ON root.run_id = lifecycle.root_run_id "
                "ORDER BY lifecycle.created_at DESC, lifecycle.lifecycle_id DESC"
            ).fetchall()
        return [self._lifecycle(row) for row in rows]

    def has_active_runs(self, lifecycle_id: str) -> bool:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM runtime_workflow_runs WHERE lifecycle_id = ? "
                "AND status IN ('pending', 'running') LIMIT 1",
                (lifecycle_id,),
            ).fetchone()
        return row is not None

    def mark_fully_terminal(self, lifecycle_id: str, *, terminal_at: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_lifecycles SET fully_terminal_at = ? "
                "WHERE lifecycle_id = ? AND fully_terminal_at IS NULL",
                (terminal_at, lifecycle_id),
            )
        return cursor.rowcount > 0

    def mark_deleting(self, lifecycle_id: str, *, started_at: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_lifecycles SET lifecycle_status = 'deleting', "
                "deletion_started_at = ? WHERE lifecycle_id = ?",
                (started_at, lifecycle_id),
            )
        return cursor.rowcount > 0

    def mark_purge_pending(self, lifecycle_id: str, *, started_at: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_lifecycles SET lifecycle_status = 'purge_pending', "
                "deletion_started_at = COALESCE(deletion_started_at, ?) "
                "WHERE lifecycle_id = ? AND lifecycle_status != 'deleting'",
                (started_at, lifecycle_id),
            )
        return cursor.rowcount > 0

    def terminal_capture_enabled(self) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT lifecycle.*, root.status AS root_status "
                "FROM runtime_lifecycles AS lifecycle "
                "JOIN runtime_workflow_runs AS root "
                "ON root.run_id = lifecycle.root_run_id "
                "WHERE lifecycle.fully_terminal_at IS NOT NULL "
                "AND lifecycle.monitoring_capture_enabled = 1 "
                "AND lifecycle.lifecycle_status = 'active' "
                "ORDER BY lifecycle.fully_terminal_at DESC, "
                "lifecycle.lifecycle_id DESC"
            ).fetchall()
        return [self._lifecycle(row) for row in rows]

    def checkpoint_thread_ids(self, lifecycle_id: str) -> tuple[str, ...]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT checkpoint_thread_id FROM runtime_workflow_runs "
                "WHERE lifecycle_id = ? AND checkpoint_thread_id IS NOT NULL",
                (lifecycle_id,),
            ).fetchall()
        return tuple(str(row["checkpoint_thread_id"]) for row in rows)

    def delete_lifecycle(self, lifecycle_id: str) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM runtime_lifecycles WHERE lifecycle_id = ?",
                (lifecycle_id,),
            )
        return cursor.rowcount > 0

    def summary(self, lifecycle_id: str) -> dict[str, object]:
        runs = self.list_runs(lifecycle_id)
        counts = Counter(str(run["status"]) for run in runs)
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for run in runs:
            run_usage = run["usage"]
            assert isinstance(run_usage, dict)
            for key in usage:
                usage[key] += int(run_usage[key])
        return {
            "run_count": len(runs),
            "active_run_count": counts["pending"] + counts["running"],
            "failed_run_count": counts["failed"] + counts["interrupted"],
            "usage": usage,
        }


__all__ = [
    "TERMINAL_RUN_STATUSES",
    "RuntimeRegistryStore",
]
