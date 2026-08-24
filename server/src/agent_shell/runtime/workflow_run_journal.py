from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, message_to_dict
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent_shell.runtime.diagnostics import RuntimeDiagnosticContext, RuntimeDiagnostics
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.workflow_lifecycle import WorkflowLifecycleService


_SECRET_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "client_secret",
        "management_token",
        "password",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "secret_value",
        "x_api_key",
    }
)


def _type_name(value: object) -> str:
    value_type = value if isinstance(value, type) else type(value)
    module = getattr(value_type, "__module__", "")
    name = getattr(value_type, "__qualname__", value_type.__name__)
    return f"{module}.{name}" if module else name


def _json_safe(
    value: Any,
    *,
    active: set[int] | None = None,
    redact_secret_fields: bool = True,
) -> Any:
    """Preserve model-visible content while excluding configured secret fields."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(
            value.value,
            active=active,
            redact_secret_fields=redact_secret_fields,
        )
    if callable(getattr(value, "get_secret_value", None)):
        return "[REDACTED]"
    if isinstance(value, bytes):
        return {
            "type": "bytes",
            "base64": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Path):
        return str(value)

    active = active if active is not None else set()
    identity = id(value)
    if identity in active:
        return {"type": _type_name(value), "cycle": True}
    active.add(identity)
    try:
        if isinstance(value, BaseMessage):
            return _json_safe(
                message_to_dict(value),
                active=active,
                redact_secret_fields=False,
            )
        if isinstance(value, BaseTool):
            try:
                return _json_safe(
                    convert_to_openai_tool(value),
                    active=active,
                    redact_secret_fields=False,
                )
            except (TypeError, ValueError):
                return {"type": _type_name(value), "name": value.name}
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized_key = key.lower().replace("-", "_")
                result[key] = (
                    "[REDACTED]"
                    if redact_secret_fields
                    and normalized_key in _SECRET_FIELD_NAMES
                    else _json_safe(
                        item,
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    )
                )
            return result
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [
                _json_safe(
                    item,
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for item in value
            ]
        if isinstance(value, (set, frozenset)):
            return [
                _json_safe(
                    item,
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for item in value
            ]
        if is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: _json_safe(
                    getattr(value, field.name),
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
                for field in fields(value)
            }
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return _json_safe(
                    model_dump(mode="json"),
                    active=active,
                    redact_secret_fields=redact_secret_fields,
                )
            except (TypeError, ValueError):
                try:
                    return _json_safe(
                        model_dump(),
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    )
                except (TypeError, ValueError):
                    pass
        model_json_schema = getattr(value, "model_json_schema", None)
        if callable(model_json_schema):
            try:
                return {
                    "type": _type_name(value),
                    "schema": _json_safe(
                        model_json_schema(),
                        active=active,
                        redact_secret_fields=redact_secret_fields,
                    ),
                }
            except (TypeError, ValueError):
                pass
        return {"type": _type_name(value)}
    finally:
        active.discard(identity)


def _serialize_chat_model_request(
    serialized: object,
    messages: object,
    tags: object,
    metadata: object,
    kwargs: Mapping[str, Any],
) -> dict[str, object]:
    invocation_params = kwargs.get("invocation_params") or {}
    safe_invocation_params = _json_safe(invocation_params)
    if isinstance(invocation_params, Mapping) and "tools" in invocation_params:
        safe_invocation_params["tools"] = _json_safe(
            invocation_params["tools"],
            redact_secret_fields=False,
        )
    return {
        "capture_layer": "langchain.on_chat_model_start",
        "serialized_model": _json_safe(serialized),
        "message_batches": _json_safe(messages, redact_secret_fields=False),
        "invocation_params": safe_invocation_params,
        "options": _json_safe(kwargs.get("options") or {}),
        "tags": _json_safe(tags or []),
        "metadata": _json_safe(metadata or {}),
        "batch_size": kwargs.get("batch_size"),
    }


@dataclass(frozen=True, slots=True)
class _AgentOwner:
    agent_type: str
    agent_id: str
    agent_name: str
    workflow_node_id: str
    parent_agent_id: str = ""
    parent_agent_name: str = ""


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
        "lc_agent_name",
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
        agent_profile_ids: Mapping[str, str] | None = None,
        subagent_profile_ids: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._diagnostics = diagnostics
        self._context = context
        self._node_kinds = dict(workflow_node_kinds or {})
        self._agent_names = {
            str(key): str(value) for key, value in (agent_names or {}).items()
        }
        self._agent_profile_ids = {
            str(key): str(value)
            for key, value in (agent_profile_ids or {}).items()
        }
        self._subagent_profile_ids = {
            str(node_id): {
                str(name): str(profile_id)
                for name, profile_id in profiles.items()
            }
            for node_id, profiles in (subagent_profile_ids or {}).items()
        }
        self._spans: dict[str, dict[str, object]] = {}
        self._child_parent_spans: dict[str, str] = {
            context.run_id: context.run_id
        }
        self._synthetic_agent_spans: set[str] = set()
        self._span_agents: dict[str, _AgentOwner] = {}
        if context.agent_id:
            node_id = context.workflow_node_id
            agent_name = self._agent_names.get(node_id, "")
            if not agent_name:
                matching_nodes = [
                    candidate
                    for candidate, profile_id in self._agent_profile_ids.items()
                    if profile_id == context.agent_id
                ]
                if len(matching_nodes) == 1:
                    node_id = matching_nodes[0]
                    agent_name = self._agent_names.get(node_id, "")
            self._span_agents[context.run_id] = _AgentOwner(
                agent_type="main_agent",
                agent_id=context.agent_id,
                agent_name=agent_name or "unknown-agent",
                workflow_node_id=node_id,
            )

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
                        thread_id=self._context.checkpoint_thread_id,
                        subject_kind=subject_kind,
                        subject_id=span_id,
                        subject_name=subject_name,
                        workflow_node_id=node_id,
                        node_invocation_id=node_invocation_id,
                    ),
                )

    def _parent_agent(
        self,
        parent_run_id: object | None,
        parent_span_id: str,
    ) -> _AgentOwner | None:
        if parent_run_id is not None:
            owner = self._span_agents.get(str(parent_run_id))
            if owner is not None:
                return owner
        return self._span_agents.get(parent_span_id)

    def _main_agent_owner(
        self,
        node_id: str,
        agent_name: str,
    ) -> _AgentOwner | None:
        resolved_node_id = node_id
        profile_id = self._agent_profile_ids.get(resolved_node_id, "")
        if not profile_id and agent_name:
            matching_nodes = [
                candidate
                for candidate, candidate_name in self._agent_names.items()
                if candidate_name == agent_name
            ]
            if len(matching_nodes) == 1:
                resolved_node_id = matching_nodes[0]
                profile_id = self._agent_profile_ids.get(resolved_node_id, "")
        if not profile_id and self._context.agent_id:
            profile_id = self._context.agent_id
            resolved_node_id = self._context.workflow_node_id
        if not profile_id:
            return None
        return _AgentOwner(
            agent_type="main_agent",
            agent_id=profile_id,
            agent_name=(
                self._agent_names.get(resolved_node_id, "")
                or agent_name
                or "unknown-agent"
            ),
            workflow_node_id=resolved_node_id,
        )

    def _subagent_owner(
        self,
        agent_name: str,
        parent_owner: _AgentOwner | None,
    ) -> _AgentOwner | None:
        candidate_nodes: list[str] = []
        if parent_owner is not None:
            candidate_nodes.append(parent_owner.workflow_node_id)
        candidate_nodes.extend(
            node_id
            for node_id, profiles in self._subagent_profile_ids.items()
            if agent_name in profiles and node_id not in candidate_nodes
        )
        matches = [
            (node_id, self._subagent_profile_ids[node_id][agent_name])
            for node_id in candidate_nodes
            if agent_name in self._subagent_profile_ids.get(node_id, {})
        ]
        if not matches:
            return None
        if parent_owner is None and len(matches) != 1:
            return None
        node_id, profile_id = matches[0]
        main_owner = parent_owner
        if main_owner is not None and main_owner.agent_type == "subagent":
            main_owner = self._main_agent_owner(
                node_id,
                main_owner.parent_agent_name,
            )
        if main_owner is None:
            main_owner = self._main_agent_owner(
                node_id,
                self._agent_names.get(node_id, ""),
            )
        return _AgentOwner(
            agent_type="subagent",
            agent_id=profile_id,
            agent_name=agent_name,
            workflow_node_id=node_id,
            parent_agent_id=main_owner.agent_id if main_owner is not None else "",
            parent_agent_name=(
                main_owner.agent_name if main_owner is not None else ""
            ),
        )

    def _callback_agent_owner(
        self,
        metadata: Mapping[str, Any] | None,
        name: str,
        parent_owner: _AgentOwner | None,
    ) -> _AgentOwner | None:
        callback_metadata = metadata or {}
        node_id = str(callback_metadata.get("langgraph_node", ""))
        callback_name = str(callback_metadata.get("lc_agent_name", ""))
        if callback_name and name == callback_name:
            if (
                parent_owner is not None
                and callback_name == parent_owner.agent_name
            ):
                return parent_owner
            subagent = self._subagent_owner(callback_name, parent_owner)
            if subagent is not None:
                return subagent
            main_agent = self._main_agent_owner(node_id, callback_name)
            if main_agent is not None:
                return main_agent
        if name in self._agent_names.values():
            return self._main_agent_owner(node_id, name)
        return None

    def _fallback_agent_owner(
        self,
        metadata: Mapping[str, Any] | None,
        parent_owner: _AgentOwner | None,
    ) -> _AgentOwner:
        if parent_owner is not None:
            return parent_owner
        callback_metadata = metadata or {}
        node_id = str(callback_metadata.get("langgraph_node", ""))
        agent_name = str(callback_metadata.get("lc_agent_name", ""))
        subagent = self._subagent_owner(agent_name, None) if agent_name else None
        if subagent is not None:
            return subagent
        main_agent = self._main_agent_owner(node_id, agent_name)
        if main_agent is not None:
            return main_agent
        return _AgentOwner(
            agent_type="main_agent",
            agent_id=(
                self._context.agent_id
                or self._agent_profile_ids.get(node_id, "")
                or f"unresolved:{node_id or agent_name or 'agent'}"
            ),
            agent_name=agent_name or self._agent_names.get(node_id, "unknown-agent"),
            workflow_node_id=node_id,
        )

    def _chain_kind(
        self,
        metadata: Mapping[str, Any] | None,
        name: str,
        parent_owner: _AgentOwner | None,
    ) -> tuple[str, str, _AgentOwner | None] | None:
        node_id = str((metadata or {}).get("langgraph_node", ""))
        if node_id in self._node_kinds and name == node_id:
            owner = (
                self._main_agent_owner(node_id, self._agent_names.get(node_id, ""))
                if self._node_kinds[node_id] == "agent"
                else None
            )
            return "workflow_node", self._node_kinds[node_id], owner
        owner = self._callback_agent_owner(metadata, name, parent_owner)
        if owner is not None:
            return "agent", owner.agent_name, owner
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
        parent_span_id = self._parent_span(parent_run_id)
        parent_owner = self._parent_agent(parent_run_id, parent_span_id)
        chain = self._chain_kind(
            metadata,
            _name(serialized, kwargs),
            parent_owner,
        )
        if chain is None:
            self._child_parent_spans[span_id] = parent_span_id
            if parent_owner is not None:
                self._span_agents[span_id] = parent_owner
            return
        kind, label, owner = chain
        if kind == "agent" and parent_span_id in self._synthetic_agent_spans:
            self._child_parent_spans[span_id] = parent_span_id
            if owner is not None:
                self._span_agents[span_id] = owner
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
        if owner is not None:
            self._span_agents[span_id] = owner
            if agent_span_id := span.get("agent_span_id"):
                self._span_agents[str(agent_span_id)] = owner
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
        parent_owner = self._parent_agent(parent_run_id, parent_span_id)
        owner = self._callback_agent_owner(
            metadata,
            str((metadata or {}).get("lc_agent_name", "")),
            parent_owner,
        ) or self._fallback_agent_owner(metadata, parent_owner)
        self._spans[str(run_id)] = {
            "kind": "model",
            "name": _name(serialized, kwargs),
            "parent": parent_span_id,
            "metadata": metadata or {},
        }
        self._child_parent_spans[str(run_id)] = str(run_id)
        self._span_agents[str(run_id)] = owner
        try:
            self._lifecycle.append_model_request(
                {
                    "lifecycle_id": self._context.lifecycle_id,
                    "run_id": self._context.run_id,
                    "occurred_at": _now(),
                    "model_run_id": str(run_id),
                    "parent_span_id": parent_span_id,
                    "agent_type": owner.agent_type,
                    "agent_id": owner.agent_id,
                    "agent_name": owner.agent_name,
                    "parent_agent_id": owner.parent_agent_id,
                    "parent_agent_name": owner.parent_agent_name,
                    "workflow_node_id": owner.workflow_node_id,
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
            try:
                self._lifecycle.mark_run_observation_partial(self._context.run_id)
            except Exception:
                pass
            if self._diagnostics is not None:
                self._diagnostics.observation_error(
                    exc,
                    code="workflow_model_request_record_failed",
                    component="observability",
                    context=RuntimeDiagnosticContext(
                        request_id=self._context.request_id,
                        lifecycle_id=self._context.lifecycle_id,
                        run_id=self._context.run_id,
                        thread_id=self._context.checkpoint_thread_id,
                        subject_kind="model",
                        subject_id=str(run_id),
                        subject_name=str(self._spans[str(run_id)]["name"]),
                        workflow_node_id=owner.workflow_node_id,
                    ),
                )
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
        owner = self._parent_agent(parent_run_id, parent_span_id)
        self._spans[str(run_id)] = {
            "kind": "tool",
            "name": name,
            "parent": parent_span_id,
            "metadata": metadata or {},
        }
        self._child_parent_spans[str(run_id)] = str(run_id)
        if owner is not None:
            self._span_agents[str(run_id)] = owner
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
        self._span_agents.clear()

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
        self._span_agents.pop(span_id, None)
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
            self._span_agents.pop(str(agent_span_id), None)
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
