from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from agent_shell.runtime.context import (
    AgentRuntimeContext,
    McpToolRuntimeContext,
    WorkflowRuntimeContext,
)
from agent_shell.runtime.diagnostics import (
    RuntimeDiagnosticContext,
)
from agent_shell.runtime.errors import AgentRuntimeError, describe_exception

if TYPE_CHECKING:
    from agent_shell.runtime.diagnostics import RuntimeDiagnostics


def _diagnostic_context(runtime: object | None) -> RuntimeDiagnosticContext:
    """Read Shell scope and official execution identity from a middleware runtime."""

    context = getattr(runtime, "context", None)
    execution = getattr(runtime, "execution_info", None)
    subject_kind = ""
    subject_id = ""
    if isinstance(context, AgentRuntimeContext):
        subject_kind = "agent"
        subject_id = context.main_agent_id
    elif isinstance(context, WorkflowRuntimeContext):
        subject_kind = "workflow"
        subject_id = context.workflow_id
    elif isinstance(context, McpToolRuntimeContext):
        subject_kind = "tool"
        subject_id = context.mcp_tool_id
    return RuntimeDiagnosticContext(
        request_id=str(getattr(context, "request_id", "") or ""),
        lifecycle_id=str(getattr(context, "lifecycle_id", "") or ""),
        run_id=str(
            getattr(execution, "run_id", None) or getattr(context, "run_id", "") or ""
        ),
        thread_id=str(getattr(execution, "thread_id", None) or ""),
        subject_kind=subject_kind,
        subject_id=subject_id,
        workflow_node_id=str(getattr(context, "workflow_node_id", "") or ""),
        node_invocation_id=str(getattr(context, "node_invocation_id", "") or ""),
    )


class _ErrorFactRecorder:
    """Persist one failure fact where the exception is still alive."""

    def __init__(self, diagnostics: RuntimeDiagnostics | None) -> None:
        self._diagnostics = diagnostics

    def record(
        self,
        exc: BaseException,
        *,
        code: str,
        request: object,
    ) -> str:
        if self._diagnostics is None:
            return ""
        return self._diagnostics.runtime_error(
            exc,
            code=code,
            component="graph_runtime",
            context=_diagnostic_context(getattr(request, "runtime", None)),
        )

    async def arecord(
        self,
        exc: BaseException,
        *,
        code: str,
        request: object,
    ) -> str:
        if self._diagnostics is None:
            return ""
        return await self._diagnostics.aruntime_error(
            exc,
            code=code,
            component="graph_runtime",
            context=_diagnostic_context(getattr(request, "runtime", None)),
        )


def _provider_error(exc: Exception, *, diagnostic_id: str = "") -> AgentRuntimeError:
    status_code = 502
    current: BaseException | None = exc
    for _depth in range(6):
        if current is None:
            break
        status = getattr(current, "status_code", None)
        if not isinstance(status, int):
            status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(status, int) and 400 <= status <= 599:
            status_code = status
            break
        current = current.__cause__ or current.__context__
    return AgentRuntimeError(
        "provider_request_failed",
        describe_exception(exc),
        status_code=status_code,
        source_exception_type=type(exc).__name__,
        diagnostic_id=diagnostic_id,
    )


class ToolErrorBoundaryMiddleware(AgentMiddleware):
    """Classify exceptions from the selected tool without changing its result."""

    def __init__(self, *, runtime_diagnostics: RuntimeDiagnostics | None = None) -> None:
        super().__init__()
        self._facts = _ErrorFactRecorder(runtime_diagnostics)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        try:
            return handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            diagnostic_id = self._facts.record(
                exc,
                code="tool_execution_failed",
                request=request,
            )
            raise AgentRuntimeError(
                "tool_execution_failed",
                describe_exception(exc),
                status_code=502,
                source_exception_type=type(exc).__name__,
                diagnostic_id=diagnostic_id,
            ) from exc

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        try:
            return await handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            diagnostic_id = await self._facts.arecord(
                exc,
                code="tool_execution_failed",
                request=request,
            )
            raise AgentRuntimeError(
                "tool_execution_failed",
                describe_exception(exc),
                status_code=502,
                source_exception_type=type(exc).__name__,
                diagnostic_id=diagnostic_id,
            ) from exc


class ProviderErrorBoundaryMiddleware(AgentMiddleware):
    """Classify exceptions from the innermost model/provider call only."""

    def __init__(self, *, runtime_diagnostics: RuntimeDiagnostics | None = None) -> None:
        super().__init__()
        self._facts = _ErrorFactRecorder(runtime_diagnostics)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        try:
            return handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            diagnostic_id = self._facts.record(
                exc,
                code="provider_request_failed",
                request=request,
            )
            raise _provider_error(exc, diagnostic_id=diagnostic_id) from exc

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        try:
            return await handler(request)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            diagnostic_id = await self._facts.arecord(
                exc,
                code="provider_request_failed",
                request=request,
            )
            raise _provider_error(exc, diagnostic_id=diagnostic_id) from exc
