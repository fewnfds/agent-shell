from __future__ import annotations

import json
import math
import sqlite3
from typing import Literal

from agent_shell.storage.database import SQLiteDatabase


ScopeKind = Literal["lifecycle", "workflow", "run"]


def _object(value: str) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("persisted monitoring JSON must contain an object")
    return decoded


def _run(row: sqlite3.Row) -> dict[str, object]:
    monitoring = None
    if "graph_status" in row.keys() and row["graph_status"] is not None:
        monitoring = {
            "graph": str(row["graph_status"]),
            "node": str(row["node_status"]),
            "protocol": str(row["protocol_status"]),
            "model": str(row["model_status"]),
            "command": str(row["command_status"]),
            "created_at": str(row["monitoring_created_at"]),
            "updated_at": str(row["monitoring_updated_at"]),
        }
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
        "monitoring": monitoring,
    }


class RuntimeMonitoringQueryStore:
    """Read concrete runtime-monitoring views from application SQLite."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    @staticmethod
    def _run_select() -> str:
        return (
            "SELECT runs.*, monitoring.graph_status, monitoring.node_status, "
            "monitoring.protocol_status, monitoring.model_status, "
            "monitoring.command_status, "
            "monitoring.created_at AS monitoring_created_at, "
            "monitoring.updated_at AS monitoring_updated_at "
            "FROM runtime_workflow_runs AS runs "
            "LEFT JOIN runtime_run_monitoring AS monitoring "
            "ON monitoring.run_id = runs.run_id "
        )

    @staticmethod
    def _scope_cte(
        lifecycle_id: str,
        kind: ScopeKind,
        selector_id: str | None,
    ) -> tuple[str, tuple[object, ...]]:
        if kind == "lifecycle":
            return (
                "WITH selected_runs(run_id) AS ("
                "SELECT run_id FROM runtime_workflow_runs "
                "WHERE lifecycle_id = ?"
                ") ",
                (lifecycle_id,),
            )
        if not selector_id:
            raise ValueError("the monitoring selector ID must not be empty")
        if kind == "run":
            return (
                "WITH selected_runs(run_id) AS ("
                "SELECT run_id FROM runtime_workflow_runs "
                "WHERE lifecycle_id = ? AND run_id = ?"
                ") ",
                (lifecycle_id, selector_id),
            )
        if kind == "workflow":
            return (
                "WITH RECURSIVE selected_runs(run_id) AS ("
                "SELECT run_id FROM runtime_workflow_runs "
                "WHERE lifecycle_id = ? AND workflow_id = ? "
                "UNION "
                "SELECT child.run_id FROM runtime_workflow_runs AS child "
                "JOIN selected_runs AS parent "
                "ON child.parent_run_id = parent.run_id "
                "WHERE child.lifecycle_id = ?"
                ") ",
                (lifecycle_id, selector_id, lifecycle_id),
            )
        raise ValueError("unknown monitoring scope kind")

    def lifecycle(self, lifecycle_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT lifecycle.*, root.status AS root_status "
                "FROM runtime_lifecycles AS lifecycle "
                "JOIN runtime_workflow_runs AS root "
                "ON root.run_id = lifecycle.root_run_id "
                "WHERE lifecycle.lifecycle_id = ?",
                (lifecycle_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "lifecycle_id": str(row["lifecycle_id"]),
            "request_id": str(row["request_id"]),
            "root_run_id": str(row["root_run_id"]),
            "workflow_id": str(row["workflow_id"]),
            "workflow_name": str(row["workflow_name"]),
            "created_at": str(row["created_at"]),
            "lifecycle_status": str(row["lifecycle_status"]),
            "root_status": str(row["root_status"]),
            "monitoring_capture_enabled": bool(row["monitoring_capture_enabled"]),
            "fully_terminal_at": row["fully_terminal_at"],
            "message_count": int(row["message_count"]),
        }

    def run(self, lifecycle_id: str, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                self._run_select()
                + "WHERE runs.lifecycle_id = ? AND runs.run_id = ?",
                (lifecycle_id, run_id),
            ).fetchone()
        return _run(row) if row is not None else None

    def workflow_exists(self, lifecycle_id: str, workflow_id: str) -> bool:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT 1 FROM runtime_workflow_runs "
                "WHERE lifecycle_id = ? AND workflow_id = ? LIMIT 1",
                (lifecycle_id, workflow_id),
            ).fetchone()
        return row is not None

    def scope_runs(
        self,
        lifecycle_id: str,
        *,
        kind: ScopeKind,
        selector_id: str | None = None,
    ) -> list[dict[str, object]]:
        cte, parameters = self._scope_cte(lifecycle_id, kind, selector_id)
        with self._database.transaction() as connection:
            rows = connection.execute(
                cte
                + self._run_select()
                + "JOIN selected_runs ON selected_runs.run_id = runs.run_id "
                "ORDER BY runs.created_at, runs.run_id",
                parameters,
            ).fetchall()
        return [_run(row) for row in rows]

    def graph(self, lifecycle_id: str, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_run_graphs "
                "WHERE lifecycle_id = ? AND run_id = ?",
                (lifecycle_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "lifecycle_id": str(row["lifecycle_id"]),
            "workflow_id": str(row["workflow_id"]),
            "workflow_name": str(row["workflow_name"]),
            "document_sha": str(row["document_sha"]),
            "document": _object(str(row["document_json"])),
            "created_at": str(row["created_at"]),
        }

    def scope_node_attempt_status_counts(
        self,
        lifecycle_id: str,
        *,
        kind: ScopeKind,
        selector_id: str | None = None,
    ) -> dict[str, int]:
        cte, parameters = self._scope_cte(lifecycle_id, kind, selector_id)
        with self._database.transaction() as connection:
            rows = connection.execute(
                cte
                + "SELECT attempts.status, COUNT(*) AS count "
                "FROM runtime_node_attempts AS attempts "
                "JOIN selected_runs ON selected_runs.run_id = attempts.run_id "
                "GROUP BY attempts.status ORDER BY attempts.status",
                parameters,
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def node_summaries(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> dict[str, object]:
        having = ""
        parameters: list[object] = [lifecycle_id, run_id]
        if status:
            having = (
                " HAVING SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) > 0"
            )
            parameters.append(status)
        base = (
            " FROM runtime_node_attempts "
            "WHERE lifecycle_id = ? AND run_id = ? "
            "GROUP BY workflow_node_id"
            + having
        )
        offset = (page - 1) * page_size
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM (SELECT workflow_node_id" + base + ")",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT workflow_node_id, MIN(sequence) AS first_sequence, "
                "MAX(sequence) AS latest_sequence, MIN(started_at) AS first_started_at, "
                "MAX(started_at) AS latest_started_at, "
                "SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running, "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
                "SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled, "
                "SUM(CASE WHEN status = 'interrupted' THEN 1 ELSE 0 END) "
                "AS interrupted, "
                "SUM(CASE WHEN status = 'incomplete' THEN 1 ELSE 0 END) "
                "AS incomplete"
                + base
                + " ORDER BY first_sequence LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        statuses = (
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
            "incomplete",
        )
        return {
            "items": [
                {
                    "workflow_node_id": str(row["workflow_node_id"]),
                    "first_sequence": int(row["first_sequence"]),
                    "latest_sequence": int(row["latest_sequence"]),
                    "first_started_at": str(row["first_started_at"]),
                    "latest_started_at": str(row["latest_started_at"]),
                    "attempt_count": sum(int(row[name]) for name in statuses),
                    "status_counts": {
                        name: int(row[name])
                        for name in statuses
                        if int(row[name]) > 0
                    },
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 1,
        }

    @staticmethod
    def _attempt(row: sqlite3.Row) -> dict[str, object]:
        return {
            "sequence": int(row["sequence"]),
            "lifecycle_id": str(row["lifecycle_id"]),
            "run_id": str(row["run_id"]),
            "workflow_node_id": str(row["workflow_node_id"]),
            "invocation_id": str(row["invocation_id"]),
            "attempt": int(row["attempt"]),
            "node_first_attempt_time": row["node_first_attempt_time"],
            "started_at": str(row["started_at"]),
            "finished_at": row["finished_at"],
            "status": str(row["status"]),
            "error_code": str(row["error_code"]),
        }

    def node_attempts(
        self,
        lifecycle_id: str,
        run_id: str,
        node_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> dict[str, object]:
        clauses = [
            "lifecycle_id = ?",
            "run_id = ?",
            "workflow_node_id = ?",
        ]
        parameters: list[object] = [lifecycle_id, run_id, node_id]
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_node_attempts WHERE " + where,
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM runtime_node_attempts WHERE "
                + where
                + " ORDER BY sequence LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        return {
            "items": [self._attempt(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 1,
        }

    def invocation_attempts(
        self,
        lifecycle_id: str,
        run_id: str,
        invocation_id: str,
    ) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_node_attempts "
                "WHERE lifecycle_id = ? AND run_id = ? AND invocation_id = ? "
                "ORDER BY attempt",
                (lifecycle_id, run_id, invocation_id),
            ).fetchall()
        return [self._attempt(row) for row in rows]

    def protocol_events(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
        method: str | None = None,
    ) -> dict[str, object]:
        clauses = [
            "lifecycle_id = ?",
            "run_id = ?",
            "event_sequence > ?",
        ]
        parameters: list[object] = [lifecycle_id, run_id, after_sequence]
        if method:
            clauses.append("method = ?")
            parameters.append(method)
        where = " AND ".join(clauses)
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_protocol_events WHERE " + where,
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM runtime_protocol_events WHERE "
                + where
                + " ORDER BY event_sequence LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        items = [
            {
                "sequence": int(row["event_sequence"]),
                "method": str(row["method"]),
                "captured_at": str(row["captured_at"]),
                "envelope": _object(str(row["envelope_json"])),
            }
            for row in rows
        ]
        return {
            "items": items,
            "after_sequence": after_sequence,
            "next_after_sequence": (
                int(items[-1]["sequence"]) if items else after_sequence
            ),
            "limit": limit,
            "remaining": max(total - len(items), 0),
        }

    def model_requests(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> dict[str, object]:
        clauses = ["lifecycle_id = ?", "run_id = ?"]
        parameters: list[object] = [lifecycle_id, run_id]
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        where = " AND ".join(clauses)
        offset = (page - 1) * page_size
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_model_requests WHERE " + where,
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM runtime_model_requests WHERE "
                + where
                + " ORDER BY sequence LIMIT ? OFFSET ?",
                (*parameters, page_size, offset),
            ).fetchall()
        return {
            "items": [
                {
                    "sequence": int(row["sequence"]),
                    "model_run_id": str(row["model_run_id"]),
                    "started_at": str(row["started_at"]),
                    "finished_at": row["finished_at"],
                    "status": str(row["status"]),
                    "error_code": str(row["error_code"]),
                    "request": _object(str(row["request_json"])),
                    "usage": _object(str(row["usage_json"])),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": math.ceil(total / page_size) if total else 1,
        }

    def command_observations(
        self,
        lifecycle_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
        node_id: str | None = None,
        phase: str | None = None,
    ) -> dict[str, object]:
        clauses = ["lifecycle_id = ?", "run_id = ?", "sequence > ?"]
        parameters: list[object] = [lifecycle_id, run_id, after_sequence]
        if node_id:
            clauses.append("workflow_node_id = ?")
            parameters.append(node_id)
        if phase:
            clauses.append("phase = ?")
            parameters.append(phase)
        where = " AND ".join(clauses)
        with self._database.transaction() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runtime_command_observations WHERE "
                    + where,
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM runtime_command_observations WHERE "
                + where
                + " ORDER BY sequence LIMIT ?",
                (*parameters, limit),
            ).fetchall()
        items = [
            {
                "sequence": int(row["sequence"]),
                "invocation_id": str(row["invocation_id"]),
                "workflow_node_id": str(row["workflow_node_id"]),
                "attempt": int(row["attempt"]),
                "occurred_at": str(row["occurred_at"]),
                "phase": str(row["phase"]),
                "error_code": str(row["error_code"]),
                "payload": _object(str(row["payload_json"])),
            }
            for row in rows
        ]
        return {
            "items": items,
            "after_sequence": after_sequence,
            "next_after_sequence": (
                int(items[-1]["sequence"]) if items else after_sequence
            ),
            "limit": limit,
            "remaining": max(total - len(items), 0),
        }


__all__ = ["RuntimeMonitoringQueryStore", "ScopeKind"]
