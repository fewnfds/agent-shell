from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from langchain_core.callbacks import BaseCallbackHandler

from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.json_values import json_safe
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


def _serialize_chat_model_request(
    serialized: object,
    messages: object,
    tags: object,
    metadata: object,
    kwargs: Mapping[str, Any],
) -> dict[str, object]:
    invocation_params = kwargs.get("invocation_params") or {}
    safe_invocation_params = json_safe(invocation_params)
    if isinstance(invocation_params, Mapping) and "tools" in invocation_params:
        safe_invocation_params["tools"] = json_safe(
            invocation_params["tools"],
            redact_secret_fields=False,
        )
    return {
        "capture_layer": "langchain.on_chat_model_start",
        "serialized_model": json_safe(serialized),
        "message_batches": json_safe(messages),
        "invocation_params": safe_invocation_params,
        "options": json_safe(kwargs.get("options") or {}),
        "tags": json_safe(tags or []),
        "metadata": json_safe(metadata or {}),
        "batch_size": kwargs.get("batch_size"),
    }


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


class ModelRequestRecorder(BaseCallbackHandler):
    """Persist only the real LangChain ChatModel request boundary."""

    def __init__(
        self,
        lifecycle: WorkflowLifecycleService,
        diagnostics: RuntimeDiagnostics | None,
        identity: WorkflowRunIdentity,
    ) -> None:
        self._lifecycle = lifecycle
        self._diagnostics = diagnostics
        self._identity = identity
        self._failed = False

    def _error(self, exc: BaseException, model_run_id: str) -> None:
        if self._failed:
            return
        self._failed = True
        try:
            self._lifecycle.mark_monitoring_partial(
                self._identity.workflow_run_id,
                "model",
            )
        except Exception:
            pass
        if self._diagnostics is not None:
            self._diagnostics.observation_error(
                exc,
                code="runtime_model_request_record_failed",
                component="observability",
                context=RuntimeDiagnosticContext(
                    request_id=self._identity.request_id,
                    lifecycle_id=self._identity.lifecycle_id,
                    workflow_run_id=self._identity.workflow_run_id,
                    checkpoint_thread_id=self._identity.checkpoint_thread_id,
                    subject_kind="model",
                    subject_id=model_run_id,
                ),
            )

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
        if self._failed:
            return
        try:
            self._lifecycle.start_model_request(
                {
                    "lifecycle_id": self._identity.lifecycle_id,
                    "run_id": self._identity.workflow_run_id,
                    "model_run_id": str(run_id),
                    "started_at": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                    "request": _serialize_chat_model_request(
                        serialized,
                        messages,
                        tags,
                        metadata,
                        kwargs,
                    ),
                }
            )
        except Exception as exc:
            self._error(exc, str(run_id))

    on_llm_start = on_chat_model_start

    def _finish(
        self,
        run_id: object,
        *,
        status: str,
        error_code: str = "",
        response: object = None,
    ) -> None:
        if self._failed:
            return
        try:
            self._lifecycle.finish_model_request(
                str(run_id),
                status=status,
                error_code=error_code,
                usage=_usage(response),
            )
        except Exception as exc:
            self._error(exc, str(run_id))

    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, status="completed", response=response)

    def on_chat_model_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        self._finish(run_id, status="completed", response=response)

    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._finish(
            run_id,
            status="failed",
            error_code=type(error).__name__,
        )

    on_chat_model_error = on_llm_error


__all__ = ["ModelRequestRecorder"]
