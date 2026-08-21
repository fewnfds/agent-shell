from __future__ import annotations

from collections.abc import Callable
import sqlite3

from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.history_retention import HistoryRetentionStore


_TABLE = "runtime_diagnostic_events"
_OPTIONAL_FIELDS = (
    "request_id",
    "lifecycle_id",
    "run_id",
    "thread_id",
    "parent_workflow_id",
    "parent_workflow_name",
    "subject_kind",
    "subject_id",
    "subject_name",
    "workflow_node_id",
    "node_invocation_id",
    "exception_type",
)


class RuntimeDiagnosticStore:
    """Persist bounded, structured runtime failure diagnostics."""

    def __init__(
        self,
        database: SQLiteDatabase,
        history_retention: HistoryRetentionStore,
    ) -> None:
        self._database = database
        self._history_retention = history_retention
        with self._database.transaction() as connection:
            self._prune(
                connection,
                self._history_retention.get_limit_in(
                    connection, "runtime_diagnostics"
                ),
            )

    @staticmethod
    def _prune(connection: sqlite3.Connection, retention_limit: int) -> None:
        connection.execute(
            f"DELETE FROM {_TABLE} WHERE sequence NOT IN ("
            f"SELECT sequence FROM {_TABLE} ORDER BY sequence DESC LIMIT ?)",
            (retention_limit,),
        )

    @staticmethod
    def _entry(row: sqlite3.Row) -> dict[str, object]:
        entry: dict[str, object] = {
            "sequence": int(row["sequence"]),
            "diagnostic_id": row["diagnostic_id"],
            "occurred_at": row["occurred_at"],
            "severity": row["severity"],
            "code": row["code"],
            "summary": row["summary"],
            "component": row["component"],
            "detail_available": bool(row["detail_available"]),
        }
        entry.update(
            {
                field: row[field]
                for field in _OPTIONAL_FIELDS
                if row[field] is not None
            }
        )
        return entry

    def add(
        self,
        *,
        diagnostic_id: str,
        occurred_at: str,
        severity: str,
        code: str,
        summary: str,
        component: str,
        detail_available: bool,
        request_id: str | None = None,
        lifecycle_id: str | None = None,
        run_id: str | None = None,
        thread_id: str | None = None,
        parent_workflow_id: str | None = None,
        parent_workflow_name: str | None = None,
        subject_kind: str | None = None,
        subject_id: str | None = None,
        subject_name: str | None = None,
        workflow_node_id: str | None = None,
        node_invocation_id: str | None = None,
        exception_type: str | None = None,
    ) -> dict[str, object]:
        optional_values = (
            request_id,
            lifecycle_id,
            run_id,
            thread_id,
            parent_workflow_id,
            parent_workflow_name,
            subject_kind,
            subject_id,
            subject_name,
            workflow_node_id,
            node_invocation_id,
            exception_type,
        )
        with self._database.transaction() as connection:
            cursor = connection.execute(
                f"INSERT INTO {_TABLE} ("
                "diagnostic_id, occurred_at, severity, code, summary, component, "
                "detail_available, " + ", ".join(_OPTIONAL_FIELDS) + ") "
                "VALUES (?, ?, ?, ?, ?, ?, ?, "
                + ", ".join("?" for _ in _OPTIONAL_FIELDS)
                + ")",
                (
                    diagnostic_id,
                    occurred_at,
                    severity,
                    code,
                    summary,
                    component,
                    int(detail_available),
                    *optional_values,
                ),
            )
            self._prune(
                connection,
                self._history_retention.get_limit_in(
                    connection, "runtime_diagnostics"
                ),
            )
        return {
            "sequence": int(cursor.lastrowid),
            "diagnostic_id": diagnostic_id,
            "occurred_at": occurred_at,
            "severity": severity,
            "code": code,
            "summary": summary,
            "component": component,
            "detail_available": detail_available,
            **{
                field: value
                for field, value in zip(_OPTIONAL_FIELDS, optional_values, strict=True)
                if value is not None
            },
        }

    def entries(self, *, request_id: str | None = None) -> list[dict[str, object]]:
        where = " WHERE request_id = ?" if request_id is not None else ""
        parameters = (request_id,) if request_id is not None else ()
        with self._database.transaction() as connection:
            rows = connection.execute(
                f"SELECT * FROM {_TABLE}{where} ORDER BY sequence ASC",
                parameters,
            ).fetchall()
        return [self._entry(row) for row in rows]

    def delete_entries(
        self,
        predicate: Callable[[dict[str, object]], bool],
    ) -> int:
        with self._database.transaction() as connection:
            rows = connection.execute(f"SELECT * FROM {_TABLE}").fetchall()
            sequences = [
                int(row["sequence"])
                for row in rows
                if predicate(self._entry(row))
            ]
            if sequences:
                connection.executemany(
                    f"DELETE FROM {_TABLE} WHERE sequence = ?",
                    ((sequence,) for sequence in sequences),
                )
        return len(sequences)

    def retention(self) -> dict[str, int]:
        return {
            "retention_limit": self._history_retention.get_limit(
                "runtime_diagnostics"
            ),
        }

    def set_retention(self, retention_limit: int) -> dict[str, int]:
        with self._database.transaction() as connection:
            self._history_retention.set_limit_in(
                connection, "runtime_diagnostics", retention_limit
            )
            self._prune(connection, retention_limit)
        return {
            "retention_limit": retention_limit,
        }


__all__ = ["RuntimeDiagnosticStore"]
