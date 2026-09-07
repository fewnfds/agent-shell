from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import traceback
from uuid import uuid4

from agent_shell.runtime.errors import AgentRuntimeError, describe_exception
from agent_shell.storage.runtime_diagnostic_details import (
    RuntimeDiagnosticDetailStore,
)
from agent_shell.storage.runtime_diagnostics import RuntimeDiagnosticStore


def _diagnostic_text(value: object) -> str:
    return str(value or "")


def _optional_diagnostic_text(value: object) -> str | None:
    text = _diagnostic_text(value)
    return text or None


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticContext:
    request_id: str = ""
    lifecycle_id: str = ""
    run_id: str = ""
    thread_id: str = ""
    subject_kind: str = ""
    subject_id: str = ""
    subject_name: str = ""
    workflow_node_id: str = ""
    node_invocation_id: str = ""

    def values(self) -> dict[str, str | None]:
        values = {
            key: _optional_diagnostic_text(value)
            for key, value in asdict(self).items()
        }
        return values


class RuntimeDiagnostics:
    """Persist bounded operational failures without owning runtime facts."""

    def __init__(
        self,
        publish: Callable[[dict[str, object]], None],
        *,
        store: RuntimeDiagnosticStore,
        details: RuntimeDiagnosticDetailStore,
        redact_secret_text: Callable[[str], str] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._store = store
        self._details = details
        self._publish = publish
        self._redact_secret_text = redact_secret_text or (lambda value: value)
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
        summary_source = detail_exception or exc
        summary = describe_exception(summary_source)
        source_exception_type = (
            summary_source.source_exception_type
            if isinstance(summary_source, AgentRuntimeError)
            and summary_source.source_exception_type
            else type(summary_source).__name__
        )
        self._emit_exception(
            exc,
            code=code,
            component=component,
            summary=summary,
            context=context,
            detail_exception=exc if detail_exception is None else detail_exception,
            source_exception_type=source_exception_type,
        )

    async def aruntime_error(
        self,
        exc: BaseException,
        *,
        code: str,
        component: str,
        context: RuntimeDiagnosticContext | None = None,
        detail_exception: BaseException | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.runtime_error,
            exc,
            code=code,
            component=component,
            context=context,
            detail_exception=detail_exception,
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
            summary=describe_exception(exc),
            context=context,
            detail_exception=exc,
            source_exception_type=type(exc).__name__,
        )

    async def aobservation_error(
        self,
        exc: BaseException,
        *,
        code: str,
        component: str,
        context: RuntimeDiagnosticContext | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.observation_error,
            exc,
            code=code,
            component=component,
            context=context,
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
        source_exception_type: str,
    ) -> None:
        diagnostic_id = uuid4().hex
        occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        diagnostic_code = self._redact_secret_text(_diagnostic_text(code))
        diagnostic_component = self._redact_secret_text(_diagnostic_text(component))
        diagnostic_summary = self._redact_secret_text(_diagnostic_text(summary))
        diagnostic_context = {
            key: (
                self._redact_secret_text(value)
                if isinstance(value, str)
                else value
            )
            for key, value in (context or RuntimeDiagnosticContext()).values().items()
        }
        diagnostic_exception_type = _optional_diagnostic_text(source_exception_type)
        prefix = (
            f"{occurred_at} [ERROR] component={diagnostic_component} "
            f"code={diagnostic_code} "
            f"request_id={diagnostic_context['request_id'] or '-'} "
            f"lifecycle_id={diagnostic_context['lifecycle_id'] or '-'} "
            f"run_id={diagnostic_context['run_id'] or '-'}"
        )
        self._logger.error(prefix + "\n" + diagnostic_summary)

        with self._lock:
            detail_available = False
            try:
                header = "".join(
                    (
                        f"diagnostic_id={diagnostic_id}\n",
                        f"occurred_at={occurred_at}\n",
                        f"component={diagnostic_component}\n",
                        f"code={diagnostic_code}\n",
                        *(
                            f"{key}={value}\n"
                            for key, value in diagnostic_context.items()
                            if value
                        ),
                        f"exception_type={source_exception_type}\n\n",
                    )
                )
                traceback_text = "".join(
                    traceback.TracebackException.from_exception(
                        detail_exception
                    ).format(chain=True)
                )
                if (
                    isinstance(detail_exception, AgentRuntimeError)
                    and detail_exception.remote_traceback
                ):
                    traceback_text += (
                        "\nAgent Server source traceback:\n"
                        + detail_exception.remote_traceback
                    )
                detail_available = self._details.write(
                    diagnostic_id,
                    (header + self._redact_secret_text(traceback_text),),
                )
            except Exception as persistence_error:
                self._logger.error(
                    prefix
                    + "\nruntime diagnostic detail persistence failed: "
                    + self._redact_secret_text(describe_exception(persistence_error))
                )
            try:
                entry = self._store.add(
                    diagnostic_id=diagnostic_id,
                    occurred_at=occurred_at,
                    severity="error",
                    code=diagnostic_code,
                    summary=diagnostic_summary,
                    component=diagnostic_component,
                    exception_type=diagnostic_exception_type,
                    detail_available=detail_available,
                    **diagnostic_context,
                )
            except Exception as persistence_error:
                self._logger.error(
                    prefix
                    + "\nruntime diagnostic index persistence failed: "
                    + self._redact_secret_text(describe_exception(persistence_error))
                )
                try:
                    self._reconcile_details()
                except Exception as cleanup_error:
                    self._logger.error(
                        prefix
                        + "\nruntime diagnostic cleanup failed: "
                        + self._redact_secret_text(describe_exception(cleanup_error))
                    )
                return
            try:
                self._reconcile_details()
            except Exception as cleanup_error:
                self._logger.error(
                    prefix
                    + "\nruntime diagnostic cleanup failed: "
                    + self._redact_secret_text(describe_exception(cleanup_error))
                )
        self._publish({"type": "runtime_diagnostic", "entry": entry})


__all__ = ["RuntimeDiagnosticContext", "RuntimeDiagnostics"]
