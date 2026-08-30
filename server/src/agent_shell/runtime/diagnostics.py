from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import chain
import logging
from pathlib import Path
import threading
import traceback
from uuid import uuid4

from agent_shell.redaction import redact_for_boundary
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.storage.runtime_diagnostic_details import (
    RuntimeDiagnosticDetailStore,
)
from agent_shell.storage.runtime_diagnostics import RuntimeDiagnosticStore


def _safe_text(value: object) -> str:
    safe = redact_for_boundary("request-trace", str(value or ""))
    return safe if isinstance(safe, str) else "[UNAVAILABLE]"


def _optional_safe_text(value: object) -> str | None:
    text = _safe_text(value)
    return text or None


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticContext:
    request_id: str = ""
    lifecycle_id: str = ""
    workflow_run_id: str = ""
    checkpoint_thread_id: str | None = None
    parent_workflow_id: str = ""
    parent_workflow_name: str = ""
    subject_kind: str = ""
    subject_id: str = ""
    subject_name: str = ""
    workflow_node_id: str = ""
    node_invocation_id: str = ""

    def safe_values(self) -> dict[str, str | None]:
        values = {
            key: _optional_safe_text(value)
            for key, value in asdict(self).items()
        }
        values["run_id"] = values.pop("workflow_run_id")
        values["thread_id"] = values.pop("checkpoint_thread_id")
        return values


class RuntimeDiagnostics:
    """Persist bounded operational failures without owning Run history."""

    def __init__(
        self,
        publish: Callable[[dict[str, object]], None],
        *,
        store: RuntimeDiagnosticStore,
        details: RuntimeDiagnosticDetailStore,
    ) -> None:
        self._lock = threading.Lock()
        self._store = store
        self._details = details
        self._publish = publish
        self._logger = logging.getLogger(f"agent_shell.runtime.{id(self)}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        formatter = logging.Formatter("%(message)s")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self._logger.addHandler(console)
        self._reconcile_details()

    def close(self) -> None:
        for handler in tuple(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._settings() | {"entries": self._store.entries()}

    def _settings(self) -> dict[str, object]:
        return self._store.retention()

    def settings(self) -> dict[str, object]:
        with self._lock:
            return self._settings()

    def set_retention_limit(self, retention_limit: int) -> dict[str, object]:
        with self._lock:
            self._store.set_retention(retention_limit)
            self._reconcile_details()
            return self._settings()

    def delete_entries(
        self,
        predicate: Callable[[dict[str, object]], bool],
    ) -> int:
        with self._lock:
            deleted = self._store.delete_entries(predicate)
            self._reconcile_details()
            return deleted

    def detail_path(self, diagnostic_id: str) -> Path | None:
        with self._lock:
            return self._details.download_path(diagnostic_id)

    def _reconcile_details(self) -> None:
        self._details.retain(
            {
                str(entry["diagnostic_id"])
                for entry in self._store.entries()
                if entry.get("detail_available") is True
            }
        )

    def runtime_error(
        self,
        exc: BaseException,
        *,
        code: str,
        component: str,
        context: RuntimeDiagnosticContext | None = None,
        detail_exception: BaseException | None = None,
    ) -> None:
        summary = (
            _safe_text(exc.safe_message)
            if isinstance(exc, AgentRuntimeError)
            else "A runtime operation failed."
        )
        self._emit_exception(
            exc,
            code=code,
            component=component,
            summary=summary,
            context=context,
            detail_exception=exc if detail_exception is None else detail_exception,
        )

    def observation_error(
        self,
        exc: BaseException,
        *,
        code: str,
        component: str,
        context: RuntimeDiagnosticContext | None = None,
    ) -> None:
        self._emit_exception(
            exc,
            code=code,
            component=component,
            summary="Observation data could not be recorded.",
            context=context,
            detail_exception=exc,
        )

    def _emit_exception(
        self,
        exc: BaseException,
        *,
        code: str,
        component: str,
        summary: str,
        context: RuntimeDiagnosticContext | None,
        detail_exception: BaseException,
    ) -> None:
        diagnostic_id = uuid4().hex
        occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        safe_code = _safe_text(code)
        safe_component = _safe_text(component)
        safe_summary = _safe_text(summary)
        safe_context = (context or RuntimeDiagnosticContext()).safe_values()
        safe_exception_type = _optional_safe_text(type(exc).__name__)
        prefix = (
            f"{occurred_at} [ERROR] component={safe_component} code={safe_code} "
            f"request_id={safe_context['request_id'] or '-'} "
            f"lifecycle_id={safe_context['lifecycle_id'] or '-'} "
            f"run_id={safe_context['run_id'] or '-'}"
        )
        self._logger.error(prefix + "\n" + safe_summary)

        with self._lock:
            detail_available = False
            try:
                detail_available = self._details.write(
                    diagnostic_id,
                    chain(
                        (
                            f"diagnostic_id={diagnostic_id}\n",
                            f"occurred_at={occurred_at}\n",
                            f"component={safe_component}\n",
                            f"code={safe_code}\n",
                            *(f"{key}={value}\n" for key, value in safe_context.items() if value),
                            f"exception_type={type(exc).__name__}\n\n",
                        ),
                        traceback.TracebackException.from_exception(
                            detail_exception
                        ).format(chain=True),
                    ),
                )
            except Exception:
                self._logger.error(prefix + "\nruntime diagnostic detail persistence failed")
            try:
                entry = self._store.add(
                    diagnostic_id=diagnostic_id,
                    occurred_at=occurred_at,
                    severity="error",
                    code=safe_code,
                    summary=safe_summary,
                    component=safe_component,
                    exception_type=safe_exception_type,
                    detail_available=detail_available,
                    **safe_context,
                )
            except Exception:
                self._logger.error(prefix + "\nruntime diagnostic index persistence failed")
                try:
                    self._reconcile_details()
                except Exception:
                    self._logger.error(prefix + "\nruntime diagnostic cleanup failed")
                return
            try:
                self._reconcile_details()
            except Exception:
                self._logger.error(prefix + "\nruntime diagnostic cleanup failed")
        self._publish({"type": "runtime_diagnostic", "entry": entry})


__all__ = ["RuntimeDiagnosticContext", "RuntimeDiagnostics"]
