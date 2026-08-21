from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from langchain_core.callbacks import BaseCallbackHandler

from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _name(serialized: object, kwargs: dict[str, Any]) -> str:
    explicit = kwargs.get("name")
    if explicit:
        return str(explicit)[:240]
    if isinstance(serialized, dict):
        if serialized.get("name"):
            return str(serialized["name"])[:240]
        identifier = serialized.get("id")
        if isinstance(identifier, (list, tuple)) and identifier:
            return str(identifier[-1])[:240]
    return "unknown"


def _metadata(value: Mapping[str, Any] | None) -> dict[str, object]:
    allowed = {
        "langgraph_node",
        "langgraph_step",
        "checkpoint_ns",
        "ls_provider",
        "ls_model_name",
        "name",
    }
    result: dict[str, object] = {}
    for key, item in (value or {}).items():
        if str(key) in allowed and isinstance(item, (str, int, float, bool)):
            result[str(key)] = item
    return result


def _usage(response: object) -> dict[str, int]:
    candidates: list[object] = []
    if isinstance(response, dict):
        candidates.extend(
            [
                response.get("usage"),
                response.get("usage_metadata"),
                response.get("response_metadata"),
                response.get("llm_output"),
            ]
        )
    else:
        for attr in ("usage_metadata", "response_metadata", "llm_output"):
            candidates.append(getattr(response, attr, None))
        for generation_group in getattr(response, "generations", ()) or ():
            for generation in generation_group or ():
                message = getattr(generation, "message", None)
                candidates.append(getattr(message, "usage_metadata", None))

    aliases = {
        "input_tokens": "input_tokens",
        "prompt_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "completion_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        nested = candidate.get("token_usage")
        if isinstance(nested, Mapping):
            candidate = nested
        result = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for source, target in aliases.items():
            value = candidate.get(source)
            if isinstance(value, (int, float)):
                result[target] = int(value)
        if any(result.values()):
            if not result["total_tokens"]:
                result["total_tokens"] = (
                    result["input_tokens"] + result["output_tokens"]
                )
            return result
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class WorkflowRunJournal(BaseCallbackHandler):
    """Write structural callback spans into the existing graph execution path."""

    def __init__(
        self,
        lifecycle: WorkflowLifecycleService,
        diagnostics: RuntimeDiagnostics | None,
        context: WorkflowRuntimeContext,
        *,
        workflow_node_kinds: Mapping[str, str] | None = None,
        agent_names: Mapping[str, str] | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._diagnostics = diagnostics
        self._context = context
        self._node_kinds = dict(workflow_node_kinds or {})
        self._agent_names = {
            str(key): str(value) for key, value in (agent_names or {}).items()
        }
        self._spans: dict[str, dict[str, object]] = {}
        self._child_parent_spans: dict[str, str] = {
            context.run_id: context.run_id
        }
        self._synthetic_agent_spans: set[str] = set()

    def _parent_span(self, parent_run_id: object | None) -> str:
        if parent_run_id is None:
            return self._context.run_id
        parent_id = str(parent_run_id)
        return self._child_parent_spans.get(parent_id, self._context.run_id)

    def _record(
        self,
        *,
        run_id: object,
        parent_run_id: object | None,
        subject_kind: str,
        subject_name: str,
        phase: str,
        event_type: str,
        metadata: Mapping[str, Any] | None = None,
        response: object = None,
        error_code: str = "",
        node_invocation_id: str = "",
    ) -> None:
        span_id = str(run_id)
        parent_span_id = str(parent_run_id) if parent_run_id else ""
        safe_metadata = _metadata(metadata)
        node_id = str(safe_metadata.get("langgraph_node", ""))
        if subject_kind == "workflow_node":
            node_invocation_id = span_id
        event = {
            "lifecycle_id": self._context.lifecycle_id,
            "run_id": self._context.run_id,
            "occurred_at": _now(),
            "event_type": event_type,
            "phase": phase,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "subject_kind": subject_kind,
            "subject_id": span_id,
            "subject_name": subject_name,
            "workflow_node_id": node_id,
            "node_invocation_id": node_invocation_id,
            "status": (
                "running"
                if phase == "started"
                else "failed"
                if phase == "failed"
                else "cancelled"
                if phase == "cancelled"
                else "completed"
            ),
            "error_code": error_code,
            "usage": _usage(response),
            "metadata": safe_metadata,
        }
        try:
            self._lifecycle.append_run_event(event)
        except Exception as exc:
            try:
                self._lifecycle.mark_run_observation_partial(self._context.run_id)
            except Exception:
                pass
            if self._diagnostics is not None:
                self._diagnostics.observation_error(
                    exc,
                    code="workflow_run_event_record_failed",
                    component="observability",
                    context=RuntimeDiagnosticContext(
                        request_id=self._context.request_id,
                        lifecycle_id=self._context.lifecycle_id,
                        run_id=self._context.run_id,
                        thread_id=self._context.thread_id,
                        subject_kind=subject_kind,
                        subject_id=span_id,
                        subject_name=subject_name,
                        workflow_node_id=node_id,
                        node_invocation_id=node_invocation_id,
                    ),
                )

    def _chain_kind(
        self,
        metadata: Mapping[str, Any] | None,
        name: str,
    ) -> tuple[str, str] | None:
        node_id = str((metadata or {}).get("langgraph_node", ""))
        if node_id in self._node_kinds and name == node_id:
            return "workflow_node", self._node_kinds[node_id]
        if name in self._agent_names.values():
            return "agent", name
        return None

    def on_chain_start(
        self,
        serialized,
        inputs,
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs,
    ):
        span_id = str(run_id)
        if span_id == self._context.run_id:
            self._child_parent_spans[span_id] = span_id
            return
        chain = self._chain_kind(metadata, _name(serialized, kwargs))
        if chain is None:
            self._child_parent_spans[span_id] = self._parent_span(parent_run_id)
            return
        kind, label = chain
        parent_span_id = self._parent_span(parent_run_id)
        if kind == "agent" and parent_span_id in self._synthetic_agent_spans:
            self._child_parent_spans[span_id] = parent_span_id
            return
        span: dict[str, object] = {
            "kind": kind,
            "name": label,
            "parent": parent_span_id,
            "metadata": metadata or {},
        }
        self._record(
            run_id=run_id,
            parent_run_id=parent_span_id,
            subject_kind=kind,
            subject_name=label,
            phase="started",
            event_type=kind,
            metadata=metadata,
        )
        node_id = str((metadata or {}).get("langgraph_node", ""))
        if (
            kind == "workflow_node"
            and label == "agent"
            and node_id in self._agent_names
        ):
            agent_span_id = f"{run_id}:agent"
            span["agent_span_id"] = agent_span_id
            self._synthetic_agent_spans.add(agent_span_id)
            self._child_parent_spans[span_id] = agent_span_id
            self._record(
                run_id=agent_span_id,
                parent_run_id=run_id,
                subject_kind="agent",
                subject_name=self._agent_names[node_id],
                phase="started",
                event_type="agent",
                metadata=metadata,
                node_invocation_id=str(run_id),
            )
        else:
            self._child_parent_spans[span_id] = span_id
        self._spans[str(run_id)] = span

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "completed")

    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "failed", error_code=type(error).__name__)

    def on_chat_model_start(
        self,
        serialized,
        messages,
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs,
    ):
        parent_span_id = self._parent_span(parent_run_id)
        self._spans[str(run_id)] = {
            "kind": "model",
            "name": _name(serialized, kwargs),
            "parent": parent_span_id,
            "metadata": metadata or {},
        }
        self._child_parent_spans[str(run_id)] = str(run_id)
        self._record(
            run_id=run_id,
            parent_run_id=parent_span_id,
            subject_kind="model",
            subject_name=str(self._spans[str(run_id)]["name"]),
            phase="started",
            event_type="model",
            metadata=metadata,
        )

    on_llm_start = on_chat_model_start

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "completed", response=response)

    def on_chat_model_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "completed", response=response)

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "failed", error_code=type(error).__name__)

    on_chat_model_error = on_llm_error

    def on_tool_start(
        self,
        serialized,
        input_str,
        *,
        run_id,
        parent_run_id=None,
        tags=None,
        metadata=None,
        **kwargs,
    ):
        name = _name(serialized, kwargs)
        parent_span_id = self._parent_span(parent_run_id)
        self._spans[str(run_id)] = {
            "kind": "tool",
            "name": name,
            "parent": parent_span_id,
            "metadata": metadata or {},
        }
        self._child_parent_spans[str(run_id)] = str(run_id)
        self._record(
            run_id=run_id,
            parent_run_id=parent_span_id,
            subject_kind="tool",
            subject_name=name,
            phase="started",
            event_type="tool",
            metadata=metadata,
        )

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "completed")

    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, "failed", error_code=type(error).__name__)

    def finish_open_spans(self, phase: str, *, error_code: str = "") -> None:
        for span_id in reversed(tuple(self._spans)):
            self._finish(span_id, phase, error_code=error_code)
        self._child_parent_spans.clear()
        self._synthetic_agent_spans.clear()

    def _finish(
        self,
        run_id: object,
        phase: str,
        *,
        response: object = None,
        error_code: str = "",
    ) -> None:
        span_id = str(run_id)
        span = self._spans.pop(span_id, None)
        self._child_parent_spans.pop(span_id, None)
        if span is None:
            return
        agent_span_id = span.get("agent_span_id")
        if agent_span_id:
            self._record(
                run_id=agent_span_id,
                parent_run_id=run_id,
                subject_kind="agent",
                subject_name=self._agent_names.get(
                    str((span.get("metadata") or {}).get("langgraph_node", "")),
                    "unknown",
                ),
                phase=phase,
                event_type="agent",
                metadata=(
                    span.get("metadata")
                    if isinstance(span.get("metadata"), Mapping)
                    else {}
                ),
                response=response,
                error_code=error_code,
                node_invocation_id=str(run_id),
            )
            self._synthetic_agent_spans.discard(str(agent_span_id))
        self._record(
            run_id=run_id,
            parent_run_id=span.get("parent"),
            subject_kind=str(span["kind"]),
            subject_name=str(span["name"]),
            phase=phase,
            event_type=str(span["kind"]),
            metadata=(
                span.get("metadata")
                if isinstance(span.get("metadata"), Mapping)
                else {}
            ),
            response=response,
            error_code=error_code,
        )


__all__ = ["WorkflowRunJournal"]
