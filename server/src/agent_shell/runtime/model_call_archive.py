from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

if TYPE_CHECKING:
    from agent_shell.storage.model_call_archive import ModelCallArchive


_LOGGER = logging.getLogger("agent_shell.model_call_archive")


def _identity(request: object) -> dict[str, object]:
    """Read Shell scope and official execution identity from the call request."""

    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None)
    execution = getattr(runtime, "execution_info", None)
    server = getattr(runtime, "server_info", None)
    return {
        "request_id": str(getattr(context, "request_id", "") or ""),
        "lifecycle_id": str(getattr(context, "lifecycle_id", "") or ""),
        "run_id": str(
            getattr(execution, "run_id", None)
            or getattr(context, "run_id", "")
            or ""
        ),
        "thread_id": str(getattr(execution, "thread_id", None) or ""),
        "task_id": str(getattr(execution, "task_id", "") or ""),
        "node_attempt": getattr(execution, "node_attempt", None),
        "assistant_id": str(getattr(server, "assistant_id", "") or ""),
    }


def _model_record(model: object) -> dict[str, object]:
    configured = (
        getattr(model, "model_name", None)
        or getattr(model, "model", None)
        or ""
    )
    return {"class": type(model).__name__, "name": str(configured)}


def _message_record(message: object) -> object | None:
    if message is None:
        return None
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:
            return repr(message)
    return repr(message)


def _message_records(messages: object) -> list[object]:
    if not isinstance(messages, (list, tuple)):
        return []
    return [
        record
        for record in (_message_record(message) for message in messages)
        if record is not None
    ]


def _tool_records(tools: object) -> list[object]:
    if not isinstance(tools, (list, tuple)):
        return []
    records: list[object] = []
    for tool in tools:
        if isinstance(tool, Mapping):
            records.append({"name": str(tool.get("name") or "")})
            continue
        schema: object = None
        args_schema = getattr(tool, "args_schema", None)
        if args_schema is not None and hasattr(args_schema, "model_json_schema"):
            try:
                schema = args_schema.model_json_schema()
            except Exception:
                schema = None
        records.append(
            {
                "name": str(getattr(tool, "name", "") or ""),
                "description": str(getattr(tool, "description", "") or ""),
                "args_schema": schema,
            }
        )
    return records


class ModelCallArchiveMiddleware(AgentMiddleware):
    """Record the real request and response of every provider attempt.

    It sits inside the provider retry boundary, so retried attempts each get
    their own record. Recording never changes the model call result.
    """

    def __init__(self, *, archive: ModelCallArchive | None = None) -> None:
        super().__init__()
        self._archive = archive

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        started = time.monotonic()
        try:
            response = handler(request)
        except Exception as exc:
            self._record(request, started, error=exc)
            raise
        self._record(request, started, response=response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        started = time.monotonic()
        try:
            response = await handler(request)
        except Exception as exc:
            await asyncio.to_thread(self._record, request, started, error=exc)
            raise
        await asyncio.to_thread(self._record, request, started, response=response)
        return response

    def _record(
        self,
        request: ModelRequest,
        started: float,
        *,
        error: BaseException | None = None,
        response: ModelResponse | None = None,
    ) -> None:
        archive = self._archive
        if archive is None:
            return
        try:
            identity = _identity(request)
            scope_id = str(
                identity["lifecycle_id"]
                or identity["request_id"]
                or "unscoped"
            )
            record: dict[str, Any] = {
                "occurred_at": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                **identity,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "model": _model_record(getattr(request, "model", None)),
                "request": {
                    "system_message": _message_record(
                        getattr(request, "system_message", None)
                    ),
                    "messages": _message_records(getattr(request, "messages", ())),
                    "tools": _tool_records(getattr(request, "tools", ())),
                    "tool_choice": getattr(request, "tool_choice", None),
                    "model_settings": dict(
                        getattr(request, "model_settings", {}) or {}
                    ),
                },
                "status": "failed" if error is not None else "succeeded",
                "response": (
                    {
                        "messages": _message_records(
                            getattr(response, "result", ())
                        ),
                        "has_structured_response": (
                            getattr(response, "structured_response", None)
                            is not None
                        ),
                    }
                    if response is not None
                    else None
                ),
                "error": (
                    {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                    if error is not None
                    else None
                ),
            }
            archive.append(scope_id, record)
        except Exception as exc:
            _LOGGER.warning(
                "model call archive write failed: %s: %s",
                type(exc).__name__,
                exc,
            )


__all__ = ["ModelCallArchiveMiddleware"]
