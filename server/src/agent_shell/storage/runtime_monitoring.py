from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Mapping

from agent_shell.storage.database import SQLiteDatabase


MONITORING_PARTITIONS = frozenset(
    {"graph", "node", "protocol", "model", "command"}
)
MONITORING_STATUSES = frozenset(
    {"capturing", "available", "partial", "not_applicable"}
)
NODE_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted", "incomplete"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


class RuntimeMonitoringStore:
    """Write runtime facts owned by the application monitoring database."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def initialize_run(
        self,
        *,
        lifecycle_id: str,
        run_id: str,
        has_executable_nodes: bool,
        has_model_nodes: bool,
        has_command_nodes: bool,
        created_at: str,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_run_monitoring ("
                "run_id, lifecycle_id, graph_status, node_status, "
                "protocol_status, model_status, command_status, "
                "created_at, updated_at) "
                "VALUES (?, ?, 'capturing', ?, 'capturing', ?, ?, ?, ?)",
                (
                    run_id,
                    lifecycle_id,
                    "capturing" if has_executable_nodes else "not_applicable",
                    "capturing" if has_model_nodes else "not_applicable",
                    "capturing" if has_command_nodes else "not_applicable",
                    created_at,
                    created_at,
                ),
            )

    def save_graph(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_run_graphs ("
                "run_id, lifecycle_id, workflow_id, workflow_name, "
                "document_sha, document_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["run_id"],
                    record["lifecycle_id"],
                    record["workflow_id"],
                    record["workflow_name"],
                    record["document_sha"],
                    _json(record["document"]),
                    record["created_at"],
                ),
            )
            connection.execute(
                "UPDATE runtime_run_monitoring SET graph_status = 'available', "
                "updated_at = ? WHERE run_id = ?",
                (record["created_at"], record["run_id"]),
            )

    def start_node_attempt(self, record: dict[str, object]) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO runtime_node_attempts ("
                "lifecycle_id, run_id, workflow_node_id, invocation_id, "
                "attempt, node_first_attempt_time, started_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'running') "
                "ON CONFLICT(run_id, invocation_id, attempt) DO NOTHING",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["workflow_node_id"],
                    record["invocation_id"],
                    int(record["attempt"]),
                    record.get("node_first_attempt_time"),
                    record["started_at"],
                ),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE runtime_run_monitoring SET updated_at = ? "
                    "WHERE run_id = ?",
                    (record["started_at"], record["run_id"]),
                )
        return cursor.rowcount > 0

    def finish_node_attempt(
        self,
        run_id: str,
        invocation_id: str,
        attempt: int,
        *,
        status: str,
        finished_at: str,
        error_code: str = "",
    ) -> bool:
        if status not in NODE_TERMINAL_STATUSES:
            raise ValueError("invalid Node attempt terminal status")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE runtime_node_attempts SET status = ?, finished_at = ?, "
                "error_code = ? WHERE run_id = ? AND invocation_id = ? "
                "AND attempt = ? AND status = 'running'",
                (
                    status,
                    finished_at,
                    error_code,
                    run_id,
                    invocation_id,
                    attempt,
                ),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE runtime_run_monitoring SET updated_at = ? "
                    "WHERE run_id = ?",
                    (finished_at, run_id),
                )
        return cursor.rowcount > 0

    def reconcile_node_attempts(self, *, finished_at: str) -> int:
        """Settle stale attempts using only the owning Run's persisted status."""

        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT DISTINCT attempts.run_id, runs.status "
                "FROM runtime_node_attempts AS attempts "
                "JOIN runtime_workflow_runs AS runs ON runs.run_id = attempts.run_id "
                "WHERE attempts.status = 'running' "
                "AND runs.status NOT IN ('pending', 'running')"
            ).fetchall()
            updated = 0
            for row in rows:
                run_id = str(row["run_id"])
                node_status = (
                    "interrupted" if str(row["status"]) == "interrupted" else "incomplete"
                )
                cursor = connection.execute(
                    "UPDATE runtime_node_attempts SET status = ?, finished_at = ?, "
                    "error_code = 'terminal_boundary_missing' "
                    "WHERE run_id = ? AND status = 'running'",
                    (node_status, finished_at, run_id),
                )
                updated += cursor.rowcount
                if cursor.rowcount:
                    connection.execute(
                        "UPDATE runtime_run_monitoring SET node_status = 'partial', "
                        "updated_at = ? WHERE run_id = ?",
                        (finished_at, run_id),
                    )
        return updated

    def append_protocol_event(
        self,
        *,
        lifecycle_id: str,
        run_id: str,
        event: Mapping[str, object],
        captured_at: str | None = None,
    ) -> None:
        sequence = event.get("seq")
        method = event.get("method")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("the v3 ProtocolEvent must have a positive seq")
        if not isinstance(method, str) or not method:
            raise ValueError("the v3 ProtocolEvent must have a method")
        occurred_at = captured_at or _now()
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_protocol_events ("
                "lifecycle_id, run_id, event_sequence, method, captured_at, "
                "envelope_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lifecycle_id,
                    run_id,
                    sequence,
                    method,
                    occurred_at,
                    _json(dict(event)),
                ),
            )
            connection.execute(
                "UPDATE runtime_run_monitoring SET updated_at = ? WHERE run_id = ?",
                (occurred_at, run_id),
            )

    def start_model_request(self, record: dict[str, object]) -> bool:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO runtime_model_requests ("
                "lifecycle_id, run_id, model_run_id, started_at, status, "
                "request_json) VALUES (?, ?, ?, ?, 'running', ?) "
                "ON CONFLICT(model_run_id) DO NOTHING",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["model_run_id"],
                    record["started_at"],
                    _json(record["request"]),
                ),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE runtime_run_monitoring SET updated_at = ? "
                    "WHERE run_id = ?",
                    (record["started_at"], record["run_id"]),
                )
        return cursor.rowcount > 0

    def finish_model_request(
        self,
        model_run_id: str,
        *,
        status: str,
        finished_at: str,
        error_code: str = "",
        usage: Mapping[str, int] | None = None,
    ) -> bool:
        if status not in {"completed", "failed"}:
            raise ValueError("invalid Model Request terminal status")
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT run_id FROM runtime_model_requests "
                "WHERE model_run_id = ? AND status = 'running'",
                (model_run_id,),
            ).fetchone()
            if row is None:
                return False
            cursor = connection.execute(
                "UPDATE runtime_model_requests SET status = ?, finished_at = ?, "
                "error_code = ?, usage_json = ? WHERE model_run_id = ? "
                "AND status = 'running'",
                (status, finished_at, error_code, _json(usage or {}), model_run_id),
            )
            if cursor.rowcount:
                connection.execute(
                    "UPDATE runtime_run_monitoring SET updated_at = ? "
                    "WHERE run_id = ?",
                    (finished_at, str(row["run_id"])),
                )
        return cursor.rowcount > 0

    def append_command_observation(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_command_observations ("
                "lifecycle_id, run_id, invocation_id, workflow_node_id, "
                "attempt, occurred_at, phase, error_code, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["invocation_id"],
                    record["workflow_node_id"],
                    int(record["attempt"]),
                    record["occurred_at"],
                    record["phase"],
                    record.get("error_code") or "",
                    _json(record.get("payload") or {}),
                ),
            )
            connection.execute(
                "UPDATE runtime_run_monitoring SET updated_at = ? WHERE run_id = ?",
                (record["occurred_at"], record["run_id"]),
            )

    def mark_partition(
        self,
        run_id: str,
        partition: str,
        status: str,
        *,
        updated_at: str | None = None,
    ) -> None:
        if partition not in MONITORING_PARTITIONS:
            raise ValueError("unknown monitoring partition")
        if status not in MONITORING_STATUSES:
            raise ValueError("unknown monitoring partition status")
        with self._database.transaction() as connection:
            connection.execute(
                f"UPDATE runtime_run_monitoring SET {partition}_status = ?, "
                "updated_at = ? WHERE run_id = ?",
                (status, updated_at or _now(), run_id),
            )

    def finish_run(self, run_id: str, *, interrupted: bool = False) -> None:
        finished_at = _now()
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT graph_status, node_status, protocol_status, "
                "model_status, command_status "
                "FROM runtime_run_monitoring WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            stale_node_status = "interrupted" if interrupted else "incomplete"
            stale_nodes = connection.execute(
                "UPDATE runtime_node_attempts SET status = ?, finished_at = ?, "
                "error_code = 'terminal_boundary_missing' "
                "WHERE run_id = ? AND status = 'running'",
                (stale_node_status, finished_at, run_id),
            ).rowcount
            model_incomplete = connection.execute(
                "SELECT 1 FROM runtime_model_requests WHERE run_id = ? "
                "AND status = 'running' LIMIT 1",
                (run_id,),
            ).fetchone() is not None
            command_incomplete = connection.execute(
                "SELECT 1 FROM runtime_command_observations AS started "
                "WHERE started.run_id = ? AND started.phase = 'started' "
                "AND NOT EXISTS ("
                "SELECT 1 FROM runtime_command_observations AS terminal "
                "WHERE terminal.run_id = started.run_id "
                "AND terminal.invocation_id = started.invocation_id "
                "AND terminal.attempt = started.attempt "
                "AND terminal.phase IN ('completed', 'failed', 'cancelled')"
                ") LIMIT 1",
                (run_id,),
            ).fetchone() is not None

            def finalize(partition: str, *, incomplete: bool = False) -> str:
                current = str(row[f"{partition}_status"])
                if current != "capturing":
                    return current
                if partition == "graph" or interrupted or incomplete:
                    return "partial"
                return "available"

            connection.execute(
                "UPDATE runtime_run_monitoring SET "
                "graph_status = ?, node_status = ?, protocol_status = ?, "
                "model_status = ?, command_status = ?, updated_at = ? "
                "WHERE run_id = ?",
                (
                    finalize("graph"),
                    finalize("node", incomplete=stale_nodes > 0),
                    finalize("protocol"),
                    finalize("model", incomplete=model_incomplete),
                    finalize("command", incomplete=command_incomplete),
                    finished_at,
                    run_id,
                ),
            )

    def status(self, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_run_monitoring WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": str(row["run_id"]),
            "lifecycle_id": str(row["lifecycle_id"]),
            "graph": str(row["graph_status"]),
            "node": str(row["node_status"]),
            "protocol": str(row["protocol_status"]),
            "model": str(row["model_status"]),
            "command": str(row["command_status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def purge_lifecycle(self, lifecycle_id: str) -> None:
        # All fact tables cascade from the Registry Lifecycle. This explicit
        # method keeps the cross-owner cleanup step visible and idempotent.
        with self._database.transaction() as connection:
            for table in (
                "runtime_command_observations",
                "runtime_model_requests",
                "runtime_protocol_events",
                "runtime_node_attempts",
                "runtime_run_graphs",
                "runtime_run_monitoring",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE lifecycle_id = ?",
                    (lifecycle_id,),
                )


__all__ = [
    "MONITORING_PARTITIONS",
    "MONITORING_STATUSES",
    "NODE_TERMINAL_STATUSES",
    "RuntimeMonitoringStore",
]
