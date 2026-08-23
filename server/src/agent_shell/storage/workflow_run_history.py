from __future__ import annotations

from collections import Counter
import json
import sqlite3

from agent_shell.storage.database import SQLiteDatabase


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


class WorkflowRunHistoryStore:
    """Persist authoritative Run records and append-only structural events."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, object]:
        return {
            "run_id": row["run_id"],
            "lifecycle_id": row["lifecycle_id"],
            "request_id": row["request_id"],
            "thread_id": row["thread_id"],
            "run_kind": row["run_kind"],
            "target_id": row["target_id"],
            "target_name": row["target_name"],
            "parent_run_id": row["parent_run_id"],
            "launcher_id": row["launcher_id"],
            "background_task_id": row["background_task_id"],
            "run_depth": int(row["run_depth"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "finish_reason": row["finish_reason"],
            "error_code": row["error_code"],
            "usage": {
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            },
            "checkpoint_available": bool(row["checkpoint_available"]),
            "observation_status": row["observation_status"],
        }

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, object]:
        return {
            "sequence": int(row["sequence"]),
            "lifecycle_id": row["lifecycle_id"],
            "run_id": row["run_id"],
            "occurred_at": row["occurred_at"],
            "event_type": row["event_type"],
            "phase": row["phase"],
            "span_id": row["span_id"],
            "parent_span_id": row["parent_span_id"],
            "subject_kind": row["subject_kind"],
            "subject_id": row["subject_id"],
            "subject_name": row["subject_name"],
            "workflow_node_id": row["workflow_node_id"],
            "node_invocation_id": row["node_invocation_id"],
            "status": row["status"],
            "error_code": row["error_code"],
            "usage": {
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "total_tokens": int(row["total_tokens"]),
            },
            "metadata": json.loads(row["metadata_json"]),
        }

    @staticmethod
    def _model_request(row: sqlite3.Row) -> dict[str, object]:
        return {
            "sequence": int(row["sequence"]),
            "lifecycle_id": row["lifecycle_id"],
            "run_id": row["run_id"],
            "occurred_at": row["occurred_at"],
            "model_run_id": row["model_run_id"],
            "parent_span_id": row["parent_span_id"] or "",
            "agent_type": row["agent_type"],
            "agent_id": row["agent_id"],
            "agent_name": row["agent_name"],
            "parent_agent_id": row["parent_agent_id"] or "",
            "parent_agent_name": row["parent_agent_name"] or "",
            "workflow_node_id": row["workflow_node_id"] or "",
            "request": json.loads(row["payload_json"]),
        }

    @staticmethod
    def _append_in(
        connection: sqlite3.Connection,
        event: dict[str, object],
    ) -> int:
        usage = event.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        cursor = connection.execute(
            "INSERT INTO workflow_run_events ("
            "lifecycle_id, run_id, occurred_at, event_type, phase, span_id, "
            "parent_span_id, subject_kind, subject_id, subject_name, "
            "workflow_node_id, node_invocation_id, status, error_code, "
            "input_tokens, output_tokens, total_tokens, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["lifecycle_id"],
                event["run_id"],
                event["occurred_at"],
                event["event_type"],
                event["phase"],
                event.get("span_id") or None,
                event.get("parent_span_id") or None,
                event["subject_kind"],
                event.get("subject_id") or None,
                event.get("subject_name") or None,
                event.get("workflow_node_id") or None,
                event.get("node_invocation_id") or None,
                event.get("status") or "",
                event.get("error_code") or "",
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                int(usage.get("total_tokens", 0)),
                json.dumps(
                    event.get("metadata") or {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
        )
        return int(cursor.lastrowid)

    def create_run(self, record: dict[str, object], event: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO workflow_run_records ("
                "run_id, lifecycle_id, request_id, thread_id, run_kind, "
                "target_id, target_name, parent_run_id, launcher_id, "
                "background_task_id, run_depth, status, created_at, "
                "checkpoint_available, observation_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, 'available')",
                (
                    record["run_id"],
                    record["lifecycle_id"],
                    record["request_id"],
                    record["thread_id"],
                    record["run_kind"],
                    record["target_id"],
                    record["target_name"],
                    record.get("parent_run_id") or None,
                    record.get("launcher_id") or None,
                    record.get("background_task_id") or None,
                    record["run_depth"],
                    record["created_at"],
                    int(bool(record["checkpoint_available"])),
                ),
            )
            self._append_in(connection, event)

    def start_run(self, run_id: str, event: dict[str, object]) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_run_records SET status = 'running', started_at = ? "
                "WHERE run_id = ? AND status = 'pending'",
                (event["occurred_at"], run_id),
            )
            if cursor.rowcount:
                self._append_in(connection, event)
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
        event: dict[str, object],
    ) -> bool:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("invalid terminal Run status")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_run_records SET status = ?, finished_at = ?, "
                "finish_reason = ?, error_code = ?, input_tokens = ?, "
                "output_tokens = ?, total_tokens = ? "
                "WHERE run_id = ? AND status NOT IN ('completed', 'failed', 'cancelled', 'interrupted')",
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
            if cursor.rowcount:
                self._append_in(connection, event)
        return cursor.rowcount > 0

    def interrupt_active(self, *, finished_at: str) -> int:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE workflow_run_records SET status = 'interrupted', "
                "finished_at = ?, error_code = 'service_restarted' "
                "WHERE status IN ('pending', 'running')",
                (finished_at,),
            )
        return cursor.rowcount

    def append_event(self, event: dict[str, object]) -> int:
        with self._database.transaction() as connection:
            return self._append_in(connection, event)

    def mark_partial(self, run_id: str) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE workflow_run_records SET observation_status = 'partial' "
                "WHERE run_id = ?",
                (run_id,),
            )

    def append_model_request(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO workflow_model_requests ("
                "lifecycle_id, run_id, occurred_at, model_run_id, parent_span_id, "
                "agent_type, agent_id, agent_name, parent_agent_id, "
                "parent_agent_name, workflow_node_id, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(model_run_id) DO NOTHING",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["occurred_at"],
                    record["model_run_id"],
                    record.get("parent_span_id") or None,
                    record["agent_type"],
                    record["agent_id"],
                    record["agent_name"],
                    record.get("parent_agent_id") or None,
                    record.get("parent_agent_name") or None,
                    record.get("workflow_node_id") or None,
                    json.dumps(
                        record["request"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                ),
            )

    def list_model_requests(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM workflow_model_requests WHERE lifecycle_id = ?"
        parameters: tuple[object, ...] = (lifecycle_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            parameters += (run_id,)
        query += " ORDER BY sequence"
        with self._database.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._model_request(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_run_records WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._run(row) if row is not None else None

    def list_runs(self, lifecycle_id: str) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_run_records WHERE lifecycle_id = ? "
                "ORDER BY created_at, run_id",
                (lifecycle_id,),
            ).fetchall()
        return [self._run(row) for row in rows]

    def list_events(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
        node_invocation_id: str | None = None,
        event_type: str | None = None,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        clauses = ["lifecycle_id = ?", "sequence > ?"]
        parameters: list[object] = [lifecycle_id, after_sequence]
        for column, value in (
            ("run_id", run_id),
            ("node_invocation_id", node_invocation_id),
            ("event_type", event_type),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        parameters.append(limit)
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM workflow_run_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence LIMIT ?",
                parameters,
            ).fetchall()
        return [self._event(row) for row in rows]

    def count_events(self, lifecycle_id: str, *, run_id: str | None = None) -> int:
        query = "SELECT COUNT(*) FROM workflow_run_events WHERE lifecycle_id = ?"
        parameters: tuple[object, ...] = (lifecycle_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            parameters += (run_id,)
        with self._database.transaction() as connection:
            row = connection.execute(query, parameters).fetchone()
        return int(row[0]) if row is not None else 0

    def summary(self, lifecycle_id: str) -> dict[str, object]:
        runs = self.list_runs(lifecycle_id)
        statuses = Counter(str(run["status"]) for run in runs)
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for run in runs:
            for key in usage:
                usage[key] += int(run["usage"][key])  # type: ignore[index]
        observation_status = (
            "unavailable"
            if not runs
            else "partial"
            if any(run["observation_status"] == "partial" for run in runs)
            else "available"
        )
        return {
            "run_count": len(runs),
            "active_run_count": statuses["pending"] + statuses["running"],
            "failed_run_count": statuses["failed"] + statuses["interrupted"],
            "run_status_counts": dict(sorted(statuses.items())),
            "usage": usage,
            "observation_status": observation_status,
        }


__all__ = ["WorkflowRunHistoryStore"]
