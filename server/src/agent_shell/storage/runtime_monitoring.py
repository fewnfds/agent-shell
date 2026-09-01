from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from typing import Mapping

from agent_shell.storage.database import SQLiteDatabase


MONITORING_PARTITIONS = frozenset({"graph", "protocol", "model", "command"})
MONITORING_STATUSES = frozenset(
    {"capturing", "available", "partial", "not_applicable"}
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


def _object(value: str) -> dict[str, object]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("persisted monitoring JSON must contain an object")
    return decoded


class RuntimeMonitoringStore:
    """Own immutable Graph and append-only runtime monitoring facts."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def initialize_run(
        self,
        *,
        lifecycle_id: str,
        run_id: str,
        has_model_nodes: bool,
        has_command_nodes: bool,
        created_at: str,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_run_monitoring ("
                "run_id, lifecycle_id, graph_status, protocol_status, "
                "model_status, command_status, created_at, updated_at) "
                "VALUES (?, ?, 'capturing', 'capturing', ?, ?, ?, ?)",
                (
                    run_id,
                    lifecycle_id,
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
                "document_sha, document_json, node_sources_json, "
                "edge_classes_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["run_id"],
                    record["lifecycle_id"],
                    record["workflow_id"],
                    record["workflow_name"],
                    record["document_sha"],
                    _json(record["document"]),
                    _json(record["node_sources"]),
                    _json(record["edge_classes"]),
                    record["created_at"],
                ),
            )
            connection.execute(
                "UPDATE runtime_run_monitoring SET graph_status = 'available', "
                "updated_at = ? WHERE run_id = ?",
                (record["created_at"], record["run_id"]),
            )

    def graph(self, run_id: str) -> dict[str, object] | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_run_graphs WHERE run_id = ?",
                (run_id,),
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
            "node_sources": json.loads(str(row["node_sources_json"])),
            "edge_classes": json.loads(str(row["edge_classes_json"])),
            "created_at": str(row["created_at"]),
        }

    def append_transition(self, record: dict[str, object]) -> int:
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO runtime_run_transitions ("
                "lifecycle_id, run_id, occurred_at, phase, status, "
                "error_code, finish_reason, usage_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["occurred_at"],
                    record["phase"],
                    record["status"],
                    record.get("error_code") or "",
                    record.get("finish_reason") or "",
                    _json(record.get("usage") or {}),
                ),
            )
        return int(cursor.lastrowid)

    def transitions(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, object]]:
        clauses = ["lifecycle_id = ?", "sequence > ?"]
        parameters: list[object] = [lifecycle_id, after_sequence]
        if run_id is not None:
            clauses.append("run_id = ?")
            parameters.append(run_id)
        parameters.append(limit)
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_run_transitions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY sequence LIMIT ?",
                parameters,
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "lifecycle_id": str(row["lifecycle_id"]),
                "run_id": str(row["run_id"]),
                "occurred_at": str(row["occurred_at"]),
                "event_type": "run",
                "phase": str(row["phase"]),
                "subject_kind": "run",
                "status": str(row["status"]),
                "error_code": str(row["error_code"]),
                "finish_reason": str(row["finish_reason"]),
                "usage": _object(str(row["usage_json"])),
                "metadata": {},
            }
            for row in rows
        ]

    def append_protocol_event(
        self,
        *,
        lifecycle_id: str,
        run_id: str,
        event: Mapping[str, object],
        origin: Mapping[str, object],
        captured_at: str | None = None,
    ) -> None:
        sequence = event.get("seq")
        method = event.get("method")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("the v3 ProtocolEvent must have a positive seq")
        if not isinstance(method, str) or not method:
            raise ValueError("the v3 ProtocolEvent must have a method")
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_protocol_events ("
                "lifecycle_id, run_id, event_sequence, method, captured_at, "
                "envelope_json, origin_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    lifecycle_id,
                    run_id,
                    sequence,
                    method,
                    captured_at or _now(),
                    _json(dict(event)),
                    _json(dict(origin)),
                ),
            )

    def protocol_events(
        self,
        lifecycle_id: str,
        *,
        run_id: str,
    ) -> list[dict[str, object]]:
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM runtime_protocol_events "
                "WHERE lifecycle_id = ? AND run_id = ? ORDER BY event_sequence",
                (lifecycle_id, run_id),
            ).fetchall()
        return [
            {
                "envelope": _object(str(row["envelope_json"])),
                "origin": _object(str(row["origin_json"])),
                "captured_at": str(row["captured_at"]),
            }
            for row in rows
        ]

    def start_model_request(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_model_requests ("
                "lifecycle_id, run_id, model_run_id, started_at, status, "
                "agent_type, agent_id, agent_name, parent_agent_id, "
                "parent_agent_name, workflow_node_id, request_json) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(model_run_id) DO NOTHING",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["model_run_id"],
                    record["started_at"],
                    record["agent_type"],
                    record["agent_id"],
                    record["agent_name"],
                    record.get("parent_agent_id") or "",
                    record.get("parent_agent_name") or "",
                    record.get("workflow_node_id") or "",
                    _json(record["request"]),
                ),
            )

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
            cursor = connection.execute(
                "UPDATE runtime_model_requests SET status = ?, finished_at = ?, "
                "error_code = ?, usage_json = ? WHERE model_run_id = ? "
                "AND status = 'running'",
                (status, finished_at, error_code, _json(usage or {}), model_run_id),
            )
        return cursor.rowcount > 0

    def model_requests(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM runtime_model_requests WHERE lifecycle_id = ?"
        parameters: tuple[object, ...] = (lifecycle_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            parameters += (run_id,)
        query += " ORDER BY sequence"
        with self._database.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "lifecycle_id": str(row["lifecycle_id"]),
                "run_id": str(row["run_id"]),
                "model_run_id": str(row["model_run_id"]),
                "started_at": str(row["started_at"]),
                "finished_at": row["finished_at"],
                "status": str(row["status"]),
                "error_code": str(row["error_code"]),
                "agent_type": str(row["agent_type"]),
                "agent_id": str(row["agent_id"]),
                "agent_name": str(row["agent_name"]),
                "parent_agent_id": str(row["parent_agent_id"]),
                "parent_agent_name": str(row["parent_agent_name"]),
                "workflow_node_id": str(row["workflow_node_id"]),
                "request": _object(str(row["request_json"])),
                "usage": _object(str(row["usage_json"])),
            }
            for row in rows
        ]

    def append_command_observation(self, record: dict[str, object]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO runtime_command_observations ("
                "lifecycle_id, run_id, invocation_id, workflow_node_id, "
                "occurred_at, phase, error_code, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["lifecycle_id"],
                    record["run_id"],
                    record["invocation_id"],
                    record["workflow_node_id"],
                    record["occurred_at"],
                    record["phase"],
                    record.get("error_code") or "",
                    _json(record.get("payload") or {}),
                ),
            )

    def command_observations(
        self,
        lifecycle_id: str,
        *,
        run_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = "SELECT * FROM runtime_command_observations WHERE lifecycle_id = ?"
        parameters: tuple[object, ...] = (lifecycle_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            parameters += (run_id,)
        query += " ORDER BY sequence"
        with self._database.transaction() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "lifecycle_id": str(row["lifecycle_id"]),
                "run_id": str(row["run_id"]),
                "invocation_id": str(row["invocation_id"]),
                "workflow_node_id": str(row["workflow_node_id"]),
                "occurred_at": str(row["occurred_at"]),
                "phase": str(row["phase"]),
                "error_code": str(row["error_code"]),
                "payload": _object(str(row["payload_json"])),
            }
            for row in rows
        ]

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
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT graph_status, protocol_status, model_status, "
                "command_status FROM runtime_run_monitoring WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return
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
                "AND terminal.phase IN ('completed', 'failed')"
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
                "graph_status = ?, protocol_status = ?, model_status = ?, "
                "command_status = ?, "
                "updated_at = ? WHERE run_id = ?",
                (
                    finalize("graph"),
                    finalize("protocol"),
                    finalize("model", incomplete=model_incomplete),
                    finalize("command", incomplete=command_incomplete),
                    _now(),
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
                "runtime_run_graphs",
                "runtime_run_monitoring",
                "runtime_run_transitions",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE lifecycle_id = ?",
                    (lifecycle_id,),
                )


__all__ = [
    "MONITORING_PARTITIONS",
    "MONITORING_STATUSES",
    "RuntimeMonitoringStore",
]
