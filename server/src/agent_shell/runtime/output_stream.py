from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal
from datetime import datetime, timezone

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.model_response import (
    ModelResponse,
    ModelResponseTracker,
    public_finish_reason,
)
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from agent_shell.workflow.events import (
    WORKFLOW_CUSTOM_EVENT_SCHEMA,
    WorkflowCustomEventV1,
    WorkflowEventSourceV1,
)

_SUBAGENT_ERROR_STATUSES = frozenset(
    {"failed", "error", "interrupted", "cancelled", "timeout", "timed_out"}
)


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


def _timestamp(value: object) -> str:
    if isinstance(value, (int, float)):
        try:
            instant = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            pass
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _namespace(value: object) -> str:
    if isinstance(value, (list, tuple)):
        parts = [str(part) for part in value if str(part)]
        return "/".join(parts) if parts else "root"
    return str(value or "root")


def _namespace_scope(value: str) -> str:
    """Drop leaf model/tool runtime segments for cross-channel correlation."""

    parts = [part for part in value.split("/") if part]
    while parts and parts[-1].partition(":")[0] in {"model", "tools"}:
        parts.pop()
    return "/".join(parts) or "root"


def _message_text(message: object) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(parts)
    return str(content) if content is not None else ""


def _tool_message_from_result(result: object, tool_call_id: str) -> ToolMessage | None:
    if isinstance(result, ToolMessage):
        return result if str(result.tool_call_id or "") == tool_call_id else None
    if not isinstance(result, Command) or not isinstance(result.update, Mapping):
        return None
    messages = result.update.get("messages")
    if not isinstance(messages, (list, tuple)):
        return None
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and str(message.tool_call_id or "") == tool_call_id
        ):
            return message
    return None


def _tool_result_text(result: object, tool_call_id: str) -> tuple[str, str]:
    tool_message = _tool_message_from_result(result, tool_call_id)
    if tool_message is not None:
        return _message_text(tool_message), str(tool_message.name or "")
    if isinstance(result, Command):
        return "", ""
    if isinstance(result, str):
        return result, ""
    if isinstance(result, (dict, list, tuple)):
        return _json_text(result), ""
    return _message_text(result), str(getattr(result, "name", "") or "")


@dataclass(frozen=True, slots=True)
class OutputEvent:
    event_type: str
    phase: str
    sequence: int
    timestamp: str
    namespace: str = "root"
    agent_name: str = ""
    node: str = ""
    source_type: str = "agent"
    workflow_node_id: str = ""
    agent_profile_id: str = ""
    subagent_profile_id: str = ""
    message: str = ""
    data: object = field(default=None, repr=False)
    values: dict[str, str] = field(default_factory=dict)
    stream_id: str = ""
    raw_seq: int = 0
    source_key: str = ""
    cycle_key: str = ""
    workflow_event_kind: str = ""

    def output_dict(self) -> dict[str, object]:
        return {
            "event_type": self.workflow_event_kind or self.event_type,
            "phase": self.phase,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "node": self.node,
            "source_type": self.source_type,
            "workflow_node_id": self.workflow_node_id,
            "agent_profile_id": self.agent_profile_id,
            "subagent_profile_id": self.subagent_profile_id,
            "message": self.message,
            "data": self.data,
            **self.values,
        }


@dataclass(frozen=True, slots=True)
class ModelCallBoundary:
    run_key: str
    source_key: str = ""
    cycle_key: str = ""
    raw_seq: int = 0
    phase: Literal["start", "end"] = "start"


@dataclass(frozen=True, slots=True)
class MainAgentMediaBlock:
    timestamp: str
    namespace: str
    agent_name: str
    node: str
    message_id: str
    block_index: int
    content: dict[str, object]
    stream_id: str = ""
    source: WorkflowEventSourceV1 | None = None


@dataclass(slots=True)
class _MessageBlock:
    timestamp: str
    namespace: str
    agent_name: str
    node: str
    message_id: str
    source: WorkflowEventSourceV1 | None = None
    block_type: str = ""
    streamed_text: str = ""


class V3EventNormalizer:
    """Convert LangChain v3 envelopes into the product's bounded event set."""

    def __init__(
        self,
        main_agent_name: str,
        model_response_observers: tuple[Callable[[ModelResponse], None], ...] = (),
        *,
        workflow_mode: bool = False,
        workflow_sources: Mapping[str, WorkflowEventSourceV1] | None = None,
        subagent_profile_ids: Mapping[str, str] | None = None,
        main_agent_names: tuple[str, ...] | None = None,
        workflow_agent_names: Mapping[str, str] | None = None,
        workflow_subagent_profile_ids: Mapping[
            str, Mapping[str, str]
        ] | None = None,
    ) -> None:
        self._main_agent_name = main_agent_name
        self._main_agent_names = frozenset(main_agent_names or (main_agent_name,))
        self._workflow_sources = dict(workflow_sources or {})
        self._workflow_mode = workflow_mode or bool(self._workflow_sources)
        self._workflow_agent_names = dict(workflow_agent_names or {})
        self._subagent_profile_ids = dict(subagent_profile_ids or {})
        self._workflow_subagent_profile_ids = {
            node_id: dict(profile_ids)
            for node_id, profile_ids in (workflow_subagent_profile_ids or {}).items()
        }
        self._sequence = 0
        self._blocks: dict[tuple[str, int], _MessageBlock] = {}
        self._message_ids: dict[str, str] = {}
        self._message_sources: dict[str, WorkflowEventSourceV1 | None] = {}
        self._main_agent_message_runs: set[str] = set()
        self._main_agent_ai_runs: dict[str, bool] = {}
        self._public_ai_runs: dict[str, bool] = {}
        self._streamed_message_runs: set[str] = set()
        self._responses = ModelResponseTracker(model_response_observers)
        self._tool_names: dict[tuple[str, str, str], str] = {}
        self._subagent_runs: dict[str, tuple[str, str]] = {}
        self._usage_by_run: dict[str, dict[str, int]] = {}
        self._raw_seq: int = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    @property
    def main_agent_message_active(self) -> bool:
        return bool(self._main_agent_message_runs)

    @property
    def finish_reason(self) -> str:
        return public_finish_reason(self._responses.last_main_agent_finish_reason)

    @property
    def finish_reason_source(self) -> str | None:
        return self._responses.last_main_agent_finish_reason_source

    @property
    def last_main_agent_response(self) -> ModelResponse | None:
        return self._responses.last_main_agent_response

    def lifecycle(
        self,
        phase: str,
        *,
        status: str,
        finish_reason: str = "",
        error_code: str = "",
    ) -> OutputEvent:
        data = {
            "status": status,
            "finish_reason": finish_reason,
            "error_code": error_code,
        }
        return self._event(
            "lifecycle",
            phase,
            timestamp=_timestamp(None),
            message=status,
            status=status,
            finish_reason=finish_reason,
            error_code=error_code,
            data=data,
            source_type_override=("non_agent" if self._workflow_mode else ""),
            workflow_event_kind=("lifecycle" if self._workflow_mode else ""),
        )

    def feed(
        self, envelope: object
    ) -> list[OutputEvent | ModelCallBoundary | MainAgentMediaBlock]:
        if not isinstance(envelope, dict):
            return []
        method = str(envelope.get("method") or "")
        params = envelope.get("params")
        if not isinstance(params, dict):
            return []
        timestamp = _timestamp(params.get("timestamp"))
        namespace = _namespace(params.get("namespace"))
        data = params.get("data")
        raw_seq = envelope.get("seq")
        self._raw_seq = raw_seq if isinstance(raw_seq, int) and raw_seq >= 0 else 0
        try:
            if method == "messages":
                return self._message_events(
                    data, timestamp=timestamp, namespace=namespace
                )
            if method == "tools":
                return self._tool_events(data, timestamp=timestamp, namespace=namespace)
            if method == "custom" or method.startswith("custom:"):
                return self._custom_events(
                    method, data, timestamp=timestamp, namespace=namespace
                )
            if method == "lifecycle" and isinstance(data, dict):
                return self._lifecycle_events(
                    data, timestamp=timestamp, namespace=namespace
                )
            # These methods contain state, task inputs/results, checkpoints, HITL
            # payloads, or debug data and are never exposed as template variables.
            if method in {
                "values",
                "updates",
                "tasks",
                "checkpoints",
                "input",
                "input.requested",
                "debug",
            }:
                return (
                    [
                        self._non_agent_event(
                            method, data, timestamp=timestamp, namespace=namespace
                        )
                    ]
                    if self._workflow_mode
                    and not self._known_agent_scope(namespace)
                    else []
                )
            return (
                [
                    self._non_agent_event(
                        method, data, timestamp=timestamp, namespace=namespace
                    )
                ]
                if self._workflow_mode
                and not self._known_agent_scope(namespace)
                else []
            )
        finally:
            self._raw_seq = 0

    def _custom_events(
        self, method: str, data: object, *, timestamp: str, namespace: str
    ) -> list[OutputEvent]:
        source = None
        channel = method.partition(":")[2] or "custom"
        custom_data = data
        if (
            isinstance(data, dict)
            and data.get("schema_name") == WORKFLOW_CUSTOM_EVENT_SCHEMA
        ):
            source = None
            try:
                workflow_event = WorkflowCustomEventV1.model_validate(data)
            except ValidationError:
                return []
            source = workflow_event.source
            channel = workflow_event.channel
            custom_data = workflow_event.data
        serialized = _json_text(custom_data)
        message = custom_data if isinstance(custom_data, str) else serialized
        source_agent_name = (
            self._subagent_for_namespace(namespace)
            or self._workflow_agent_name(node="", namespace=namespace)
        )
        if source is None:
            source = self._source_for(
                namespace=namespace,
                node="",
                agent_name=source_agent_name,
            )
        if self._workflow_mode and isinstance(data, dict) and data.get(
            "schema_name"
        ) == WORKFLOW_CUSTOM_EVENT_SCHEMA:
            registered = self._source_for(
                namespace=namespace,
                node="",
                agent_name=source_agent_name,
            )
            if registered is not None and registered.source_type in {
                "agent",
                "subagent",
            }:
                if (
                    registered.workflow_node_id == source.workflow_node_id
                    and registered.source_type == source.source_type
                    and registered == source
                ):
                    source = registered
                elif not (
                    registered.source_type == "agent"
                    and source.source_type == "subagent"
                    and registered.agent_profile_id == source.agent_profile_id
                    and source.subagent_profile_id
                    in self._workflow_subagent_profile_ids.get(
                        registered.workflow_node_id,
                        self._subagent_profile_ids,
                    ).values()
                ):
                    source = registered
            elif registered is not None:
                source = registered
            else:
                source = None
        source_type_override = "non_agent" if source is None else ""
        return [
            self._event(
                "custom",
                "end",
                timestamp=timestamp,
                namespace=namespace,
                source=source,
                message=message,
                channel=channel,
                data_json=serialized,
                data=custom_data,
                source_type_override=source_type_override,
                workflow_event_kind=(
                    "custom"
                    if source_type_override
                    or (source is not None and source.source_type == "script")
                    else ""
                ),
            )
        ]

    def _non_agent_event(
        self,
        method: str,
        data: object,
        *,
        timestamp: str,
        namespace: str,
    ) -> OutputEvent:
        serialized = _json_text(data)
        values = (
            {
                "status": str(data.get("event") or "running"),
                "finish_reason": str(data.get("finish_reason") or ""),
                "error_code": str(data.get("error_code") or ""),
            }
            if method == "lifecycle" and isinstance(data, dict)
            else {"channel": method or "unknown", "data_json": serialized}
        )
        return self._event(
            "custom",
            "end",
            timestamp=timestamp,
            namespace=namespace,
            message=serialized,
            data=data,
            source_type_override="non_agent",
            workflow_event_kind=(
                method
                if method in {
                    "values",
                    "updates",
                    "tasks",
                    "checkpoints",
                    "input",
                    "input.requested",
                    "debug",
                    "lifecycle",
                    "custom",
                }
                else "other"
            ),
            **values,
        )

    def _lifecycle_events(
        self, data: dict[str, object], *, timestamp: str, namespace: str
    ) -> list[OutputEvent]:
        status = str(data.get("event") or "running")
        lifecycle_namespace = _namespace(data.get("namespace") or namespace)
        graph_name = str(data.get("graph_name") or "")
        cause = data.get("cause")
        tool_call_id = (
            str(cause.get("tool_call_id") or "")
            if isinstance(cause, dict)
            else ""
        )
        active_key = self._subagent_run_key(lifecycle_namespace)
        active_subagent = (
            self._subagent_runs.get(active_key) if active_key is not None else None
        )
        if active_subagent is not None and status != "started":
            subagent_name, started_tool_call_id = self._subagent_runs.pop(active_key)
            source = self._source_for(
                namespace=lifecycle_namespace,
                node="",
                agent_name=subagent_name,
            )
            return [
                self._event(
                    "subagent",
                    "error" if status in _SUBAGENT_ERROR_STATUSES else "end",
                    timestamp=timestamp,
                    namespace=lifecycle_namespace,
                    source=source,
                    source_agent_name=subagent_name,
                    message=status,
                    status=status,
                    tool_call_id=started_tool_call_id,
                    subagent_name=subagent_name,
                )
            ]

        workflow_agent_name = self._workflow_agent_name(
            node="", namespace=lifecycle_namespace
        )
        workflow_source = self._source_for(
            namespace=lifecycle_namespace,
            node=graph_name,
            agent_name=(graph_name or workflow_agent_name),
        )
        is_workflow_agent = (
            workflow_source is not None
            and workflow_source.source_type == "agent"
            and (
                not graph_name
                or graph_name in self._main_agent_names
                or graph_name == workflow_agent_name
            )
        )
        if is_workflow_agent or (
            workflow_source is not None and workflow_source.source_type == "script"
        ):
            phase = "start" if status == "started" else (
                "error" if status in _SUBAGENT_ERROR_STATUSES else "end"
            )
            return [
                self._event(
                    "lifecycle",
                    phase,
                    timestamp=timestamp,
                    namespace=lifecycle_namespace,
                    source=workflow_source,
                    message=status,
                    status=status,
                    finish_reason="",
                    error_code=("workflow_node_failed" if phase == "error" else ""),
                    data=data,
                )
            ]

        is_subagent = bool(graph_name) and (
            not self._workflow_mode
            or (
                workflow_source is not None
                and graph_name != workflow_agent_name
            )
        )
        if status == "started" and is_subagent:
            self._subagent_runs[lifecycle_namespace] = (graph_name, tool_call_id)
            return [
                self._event(
                    "subagent",
                    "start",
                    timestamp=timestamp,
                    namespace=lifecycle_namespace,
                    source=workflow_source,
                    source_agent_name=graph_name,
                    message=status,
                    status=status,
                    tool_call_id=tool_call_id,
                    subagent_name=graph_name,
                    data=data,
                )
            ]
        return (
            [
                self._non_agent_event(
                    "lifecycle",
                    data,
                    timestamp=timestamp,
                    namespace=lifecycle_namespace,
                )
            ]
            if self._workflow_mode and workflow_source is None
            else []
        )

    def _message_events(
        self, data: object, *, timestamp: str, namespace: str
    ) -> list[OutputEvent | ModelCallBoundary]:
        if not isinstance(data, (list, tuple)) or len(data) != 2:
            return []
        payload, raw_metadata = data
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        node = str(metadata.get("langgraph_node") or "")
        metadata_agent_name = str(metadata.get("lc_agent_name") or "")
        subagent_name = self._subagent_for_namespace(namespace)
        workflow_agent_name = self._workflow_agent_name(
            node=node, namespace=namespace
        )
        agent_name = (
            metadata_agent_name
            or subagent_name
            or workflow_agent_name
            or ("" if self._workflow_mode else self._main_agent_name)
        )
        source = self._source_for(
            namespace=namespace,
            node=node,
            agent_name=agent_name,
        )
        run_id = str(metadata.get("run_id") or "")
        source_key = self._source_key(source, namespace, agent_name)
        cycle_key = self._cycle_key(namespace)
        if self._workflow_mode and source is None:
            return [
                self._non_agent_event(
                    "messages", data, timestamp=timestamp, namespace=namespace
                )
            ]
        run_key = run_id or f"{source_key}:{agent_name}"
        is_main_agent = self._is_main_agent_source(
            source, agent_name=agent_name, subagent_name=subagent_name
        )
        is_public_agent = is_main_agent or (
            source is not None and source.source_type == "subagent"
        )

        if not isinstance(payload, dict):
            if not isinstance(payload, AIMessage):
                return []
            usage = getattr(payload, "usage_metadata", None)
            response_metadata = getattr(payload, "response_metadata", None)
            additional_kwargs = getattr(payload, "additional_kwargs", None)
            usage_data = usage if isinstance(usage, dict) else {}
            metadata_data = (
                response_metadata if isinstance(response_metadata, dict) else {}
            )
            additional_data = (
                additional_kwargs if isinstance(additional_kwargs, dict) else {}
            )
            content_blocks = getattr(payload, "content_blocks", None)
            self._merge_run_usage(run_key, usage_data)
            if not is_public_agent:
                return []
            if is_main_agent:
                self._responses.record(
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node=node,
                    run_id=run_id,
                    run_key=run_key,
                    message_id=str(getattr(payload, "id", "") or ""),
                    is_main_agent=True,
                    usage=usage_data,
                    response_metadata=metadata_data,
                    additional_kwargs=additional_data,
                    content_blocks=(
                        [block for block in content_blocks if isinstance(block, dict)]
                        if isinstance(content_blocks, list)
                        else []
                    ),
                )
            boundary = ModelCallBoundary(
                run_key, source_key, cycle_key, self._raw_seq
            )
            if run_key in self._streamed_message_runs:
                return [boundary, replace(boundary, phase="end")]
            return [
                boundary,
                *self._whole_message_events(
                    payload,
                    run_key=run_key,
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node=node,
                    source=source,
                ),
                replace(boundary, phase="end"),
            ]

        event_name = str(payload.get("event") or "")
        if event_name == "message-start":
            message_id = str(payload.get("id") or payload.get("message_id") or "")
            self._message_ids[run_key] = message_id
            self._message_sources[run_key] = source
            self._responses.begin(run_key, payload.get("metadata"))
            self._streamed_message_runs.add(run_key)
            is_main_agent_ai = is_main_agent and str(payload.get("role") or "ai") == "ai"
            is_public_ai = is_public_agent and str(payload.get("role") or "ai") == "ai"
            self._main_agent_ai_runs[run_key] = is_main_agent_ai
            self._public_ai_runs[run_key] = is_public_ai
            if is_main_agent_ai:
                self._main_agent_message_runs.add(run_key)
            return [
                ModelCallBoundary(
                    run_key, source_key, cycle_key, self._raw_seq
                )
            ] if is_public_ai else []
        if event_name == "message-finish":
            usage = payload.get("usage")
            usage_data = usage if isinstance(usage, dict) else {}
            response_metadata = payload.get("metadata")
            metadata_data = (
                response_metadata if isinstance(response_metadata, dict) else {}
            )
            additional_kwargs = payload.get("additional_kwargs")
            additional_data = (
                additional_kwargs if isinstance(additional_kwargs, dict) else {}
            )
            incomplete_block_count = sum(
                1 for key in self._blocks if key[0] == run_key
            )
            if incomplete_block_count:
                diagnostics = self._responses.diagnostics(run_key)
                diagnostics["incomplete_block_count"] = (
                    diagnostics.get("incomplete_block_count", 0)
                    + incomplete_block_count
                )
            self._merge_run_usage(run_key, usage_data)
            is_main_agent_message = self._main_agent_ai_runs.get(run_key, is_main_agent)
            is_public_message = self._public_ai_runs.get(
                run_key,
                is_public_agent,
            )
            if is_main_agent_message:
                self._responses.record(
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node=node,
                    run_id=run_id,
                    run_key=run_key,
                    message_id=self._message_ids.get(run_key, ""),
                    is_main_agent=True,
                    usage=usage_data,
                    response_metadata=metadata_data,
                    additional_kwargs=additional_data,
                )
            self._discard_message(run_key)
            return [
                ModelCallBoundary(
                    run_key,
                    source_key,
                    cycle_key,
                    self._raw_seq,
                    phase="end",
                )
            ] if is_public_message else []
        if event_name == "error":
            is_main_agent_message = self._main_agent_ai_runs.get(run_key, is_main_agent)
            self._discard_message(run_key)
            if is_main_agent_message:
                raise AgentRuntimeError(
                    "agent_execution_failed",
                    "The model response stream failed.",
                    status_code=502,
                )
            return []

        if not self._public_ai_runs.get(run_key, is_public_agent):
            return []

        index = payload.get("index")
        if not isinstance(index, int):
            return []
        key = (run_key, index)
        message_id = self._message_ids.get(run_key, "")
        if event_name == "content-block-start":
            content = payload.get("content")
            block_type = (
                str(content.get("type") or "") if isinstance(content, dict) else ""
            )
            self._blocks[key] = _MessageBlock(
                timestamp=timestamp,
                namespace=namespace,
                agent_name=agent_name,
                node=node,
                message_id=message_id,
                source=source,
                block_type=block_type,
            )
            diagnostics = self._responses.diagnostics(run_key)
            diagnostics["content_block_count"] = (
                diagnostics.get("content_block_count", 0) + 1
            )
            stream_id = f"{run_key}:{index}"
            if block_type in {"text", "reasoning"}:
                return [
                    self._event(
                        "reasoning"
                        if block_type == "reasoning"
                        else "assistant_text",
                        "start",
                        timestamp=timestamp,
                        namespace=namespace,
                        agent_name=agent_name,
                        node=node,
                        source=source,
                        message_id=message_id,
                        stream_id=stream_id,
                        data=content,
                    )
                ]
            if block_type in {
                "tool_call",
                "server_tool_call",
                "tool_call_chunk",
                "server_tool_call_chunk",
            } and isinstance(content, dict):
                return [
                    self._tool_call_event(
                        content,
                        phase="start",
                        timestamp=timestamp,
                        namespace=namespace,
                        agent_name=agent_name,
                        node=node,
                        source=source,
                        stream_id=stream_id,
                    )
                ]
            return []
        if event_name == "content-block-delta":
            block = self._blocks.get(key)
            delta = payload.get("delta")
            if block is None or not isinstance(delta, dict):
                return []
            fragment = self._block_text(delta)
            if not fragment or block.block_type not in {"text", "reasoning"}:
                return []
            block.streamed_text += fragment
            diagnostics = self._responses.diagnostics(run_key)
            diagnostics["delta_block_count"] = (
                diagnostics.get("delta_block_count", 0) + 1
            )
            return [
                self._event(
                    "reasoning"
                    if block.block_type == "reasoning"
                    else "assistant_text",
                    "delta",
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node=node,
                    source=block.source,
                    message=fragment,
                    message_id=message_id,
                    stream_id=f"{run_key}:{index}",
                    data=delta,
                )
            ]
        if event_name == "content-block-finish":
            content = payload.get("content")
            if not isinstance(content, dict):
                return []
            self._responses.finish_block(run_key, index, content)
            block = self._blocks.pop(
                key,
                _MessageBlock(
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node=node,
                    message_id=message_id,
                ),
            )
            block.timestamp = timestamp
            block_type = str(content.get("type") or "")
            if block.block_type in {"text", "reasoning"}:
                diagnostics = self._responses.diagnostics(run_key)
                if block_type == block.block_type:
                    complete_text = self._block_text(content)
                else:
                    complete_text = block.streamed_text
                    diagnostics["block_type_mismatch_count"] = (
                        diagnostics.get("block_type_mismatch_count", 0) + 1
                    )
                if (
                    block_type == block.block_type
                    and block.streamed_text
                    and block.streamed_text != complete_text
                ):
                    diagnostics["snapshot_mismatch_count"] = (
                        diagnostics.get("snapshot_mismatch_count", 0) + 1
                    )
                return [
                    self._event(
                        "reasoning"
                        if block.block_type == "reasoning"
                        else "assistant_text",
                        "end",
                        timestamp=block.timestamp,
                        namespace=block.namespace,
                        agent_name=block.agent_name,
                        node=block.node,
                        source=block.source,
                        message=block.streamed_text or complete_text,
                        message_id=block.message_id,
                        stream_id=f"{run_key}:{index}",
                        data=content,
                    )
                ]
            return self._finished_block_events(
                content,
                block,
                block_index=index,
                stream_id=f"{run_key}:{index}",
            )
        return []

    def _whole_message_events(
        self,
        message: object,
        *,
        run_key: str,
        timestamp: str,
        namespace: str,
        agent_name: str,
        node: str,
        source: WorkflowEventSourceV1 | None,
    ) -> list[OutputEvent | MainAgentMediaBlock]:
        message_id = str(getattr(message, "id", "") or "")
        blocks = getattr(message, "content_blocks", None)
        if not isinstance(blocks, list):
            text = _message_text(message)
            blocks = [{"type": "text", "text": text}] if text else []
        events: list[OutputEvent | MainAgentMediaBlock] = []
        for index, content in enumerate(blocks):
            if not isinstance(content, dict):
                continue
            block = _MessageBlock(
                timestamp=timestamp,
                namespace=namespace,
                agent_name=agent_name,
                node=node,
                message_id=message_id,
                source=source,
            )
            events.extend(
                self._finished_block_events(
                    content,
                    block,
                    block_index=index,
                    stream_id=f"{run_key}:{index}",
                )
            )
        return events

    def _finished_block_events(
        self,
        content: dict[str, object],
        block: _MessageBlock,
        *,
        block_index: int = 0,
        stream_id: str = "",
    ) -> list[OutputEvent | MainAgentMediaBlock]:
        block_type = str(content.get("type") or "")
        if block_type in {"text", "reasoning"}:
            return [
                self._event(
                    "reasoning" if block_type == "reasoning" else "assistant_text",
                    "end",
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    source=block.source,
                    message=self._block_text(content),
                    message_id=block.message_id,
                    data=content,
                )
            ]
        if block_type in {"image", "audio", "video", "file"}:
            return [
                MainAgentMediaBlock(
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    message_id=block.message_id,
                    block_index=block_index,
                    content=dict(content),
                    stream_id=stream_id,
                    source=block.source,
                )
            ]
        if block_type in {"tool_call", "server_tool_call"}:
            return [
                self._tool_call_event(
                    content,
                    phase="end",
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    source=block.source,
                    stream_id=stream_id,
                )
            ]
        if block_type in {"tool_call_chunk", "server_tool_call_chunk"}:
            return [
                self._event(
                    "tool_error",
                    "error",
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    source=block.source,
                    message="Tool call arguments did not finish.",
                    tool_name=str(content.get("name") or ""),
                    tool_call_id=str(content.get("id") or ""),
                    status="failed",
                    error_code="invalid_tool_call",
                    stream_id=stream_id,
                    data=content,
                )
            ]
        if block_type == "invalid_tool_call":
            return [
                self._event(
                    "tool_error",
                    "error",
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    source=block.source,
                    message="Invalid tool call arguments.",
                    tool_name=str(content.get("name") or ""),
                    tool_call_id=str(content.get("id") or ""),
                    status="failed",
                    error_code="invalid_tool_call",
                    stream_id=stream_id,
                    data=content,
                )
            ]
        if block_type == "server_tool_result":
            call_id = str(content.get("tool_call_id") or "")
            status = str(content.get("status") or "success")
            if status == "error":
                return [
                    self._event(
                        "tool_error",
                        "error",
                        timestamp=block.timestamp,
                        namespace=block.namespace,
                        agent_name=block.agent_name,
                        node=block.node,
                        source=block.source,
                        message="Server tool execution failed.",
                        tool_name=self._tool_names.pop(
                            self._tool_cache_key(
                                namespace=block.namespace,
                                node=block.node,
                                agent_name=block.agent_name,
                                call_id=call_id,
                            ),
                            "",
                        ),
                        tool_call_id=call_id,
                        status="failed",
                        error_code="server_tool_error",
                        stream_id=stream_id,
                        data=content,
                    )
                ]
            text, result_name = _tool_result_text(content.get("output"), call_id)
            stored_name = self._tool_names.pop(
                self._tool_cache_key(
                    namespace=block.namespace,
                    node=block.node,
                    agent_name=block.agent_name,
                    call_id=call_id,
                ),
                "",
            )
            name = result_name or stored_name
            return [
                self._event(
                    "tool_result",
                    "end",
                    timestamp=block.timestamp,
                    namespace=block.namespace,
                    agent_name=block.agent_name,
                    node=block.node,
                    source=block.source,
                    message=text,
                    tool_name=name,
                    tool_call_id=call_id,
                    status="completed",
                    output=text,
                    stream_id=stream_id,
                    data=content.get("output"),
                )
            ]
        return []

    def media_notification(
        self, block: MainAgentMediaBlock, message: str
    ) -> OutputEvent:
        return self._event(
            "assistant_text",
            "end",
            timestamp=block.timestamp,
            namespace=block.namespace,
            agent_name=block.agent_name,
            node=block.node,
            message=message,
            message_id=block.message_id,
            stream_id=block.stream_id,
            source=block.source,
            data=block.content,
        )

    @staticmethod
    def _block_text(content: dict[str, object]) -> str:
        block_type = str(content.get("type") or "")
        field_name = (
            "reasoning" if block_type in {"reasoning", "reasoning-delta"} else "text"
        )
        return str(content.get(field_name) or "")

    def _tool_call_event(
        self,
        tool_call: dict[str, object],
        *,
        phase: str,
        timestamp: str,
        namespace: str,
        agent_name: str,
        node: str,
        source: WorkflowEventSourceV1 | None = None,
        stream_id: str = "",
    ) -> OutputEvent:
        name = str(tool_call.get("name") or "")
        call_id = str(tool_call.get("id") or "")
        arguments = tool_call.get("args", "")
        arguments_text = (
            arguments if isinstance(arguments, str) else _json_text(arguments)
        )
        if call_id and name:
            self._tool_names[
                self._tool_cache_key(
                    namespace=namespace,
                    node=node,
                    agent_name=agent_name,
                    call_id=call_id,
                )
            ] = name
        return self._event(
            "tool_call",
            phase,
            timestamp=timestamp,
            namespace=namespace,
            agent_name=agent_name,
            node=node,
            source=source,
            message=arguments_text,
            tool_name=name,
            tool_call_id=call_id,
            arguments=arguments_text,
            stream_id=stream_id,
            data=tool_call,
        )

    def _tool_events(
        self, data: object, *, timestamp: str, namespace: str
    ) -> list[OutputEvent]:
        if not isinstance(data, dict):
            return []
        lifecycle = str(data.get("event") or "")
        call_id = str(data.get("tool_call_id") or "")
        output = data.get("output")
        result_text, result_name = _tool_result_text(output, call_id)
        subagent_name = self._subagent_for_namespace(namespace)
        agent_name = (
            subagent_name
            or self._workflow_agent_name(node="", namespace=namespace)
            or self._main_agent_name
        )
        source = self._source_for(
            namespace=namespace,
            node="tools",
            agent_name=agent_name,
        )
        if self._workflow_mode and source is None:
            return [
                self._non_agent_event(
                    "tools", data, timestamp=timestamp, namespace=namespace
                )
            ]
        tool_key = self._tool_cache_key(
            namespace=namespace,
            node="tools",
            agent_name=agent_name,
            call_id=call_id,
        )
        name = str(
            data.get("tool_name") or result_name or self._tool_names.get(tool_key, "")
        )
        if call_id and name:
            self._tool_names[tool_key] = name
        if lifecycle == "tool-started":
            return [
                self._event(
                    "tool_progress",
                    "start",
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node="tools",
                    source=source,
                    message="",
                    tool_name=name,
                    tool_call_id=call_id,
                    status="running",
                    data=data,
                )
            ]
        if lifecycle == "tool-output-delta":
            return [
                self._event(
                    "tool_progress",
                    "delta",
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node="tools",
                    source=source,
                    message="",
                    tool_name=name,
                    tool_call_id=call_id,
                    status="running",
                    data=data,
                )
            ]
        if lifecycle == "tool-finished":
            self._tool_names.pop(tool_key, None)
            return [
                self._event(
                    "tool_result",
                    "end",
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node="tools",
                    source=source,
                    message=result_text,
                    tool_name=name,
                    tool_call_id=call_id,
                    status="completed",
                    output=result_text,
                    data=output,
                )
            ]
        if "fail" in lifecycle or "error" in lifecycle:
            self._tool_names.pop(tool_key, None)
            return [
                self._event(
                    "tool_error",
                    "error",
                    timestamp=timestamp,
                    namespace=namespace,
                    agent_name=agent_name,
                    node="tools",
                    source=source,
                    message="Tool execution failed.",
                    tool_name=name,
                    tool_call_id=call_id,
                    status="failed",
                    error_code="tool_execution_failed",
                    data=data,
                )
            ]
        return []

    def _discard_message(self, run_key: str) -> None:
        for key in [item for item in self._blocks if item[0] == run_key]:
            self._blocks.pop(key, None)
        self._message_ids.pop(run_key, None)
        self._message_sources.pop(run_key, None)
        self._responses.discard(run_key)
        self._main_agent_ai_runs.pop(run_key, None)
        self._public_ai_runs.pop(run_key, None)
        self._main_agent_message_runs.discard(run_key)

    def close_main_agent_messages(self) -> None:
        """Discard normalization state after the graph stream is exhausted."""

        run_keys = self._main_agent_message_runs | {key[0] for key in self._blocks}
        for run_key in sorted(run_keys):
            self._discard_message(run_key)

    def abort_main_agent_messages(self) -> None:
        run_keys = self._main_agent_message_runs | {key[0] for key in self._blocks}
        for run_key in list(run_keys):
            self._discard_message(run_key)

    def _merge_run_usage(self, run_key: str, usage: object) -> None:
        if not isinstance(usage, dict):
            return
        current: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                current[key] = value
        output_details = usage.get("output_token_details")
        if isinstance(output_details, dict):
            reasoning = output_details.get("reasoning")
            if isinstance(reasoning, int) and reasoning >= 0:
                current["reasoning_tokens"] = reasoning
        previous = self._usage_by_run.setdefault(run_key, {})
        for key, value in current.items():
            previous_value = previous.get(key, 0)
            if value > previous_value:
                self.usage[key] = self.usage.get(key, 0) + value - previous_value
                previous[key] = value

    def _subagent_for_namespace(self, namespace: str) -> str:
        """Resolve the nearest active Deep Agent subagent scope."""

        key = self._subagent_run_key(namespace)
        return self._subagent_runs[key][0] if key is not None else ""

    def _subagent_run_key(self, namespace: str) -> str | None:
        scope = _namespace_scope(namespace)
        best: tuple[int, str] | None = None
        for run_scope, (name, _tool_call_id) in self._subagent_runs.items():
            normalized = _namespace_scope(run_scope)
            if normalized == scope or scope.startswith(normalized + "/"):
                candidate = (len(normalized), name)
                if best is None or candidate[0] > best[0]:
                    best = (candidate[0], run_scope)
        return best[1] if best is not None else None

    def _workflow_agent_name(self, *, node: str, namespace: str) -> str:
        """Map a raw node/namespace name to the frozen Workflow Agent name."""

        if node and node in self._workflow_agent_names:
            return self._workflow_agent_names[node]
        for part in reversed(namespace.split("/")):
            candidate = part.partition(":")[0]
            if candidate in self._workflow_agent_names:
                return self._workflow_agent_names[candidate]
        return ""

    def _is_main_agent_source(
        self,
        source: WorkflowEventSourceV1 | None,
        *,
        agent_name: str,
        subagent_name: str,
    ) -> bool:
        if subagent_name:
            return False
        if source is not None:
            return source.source_type == "agent"
        if self._workflow_mode:
            return False
        return agent_name in self._main_agent_names

    def _known_agent_scope(self, namespace: str) -> bool:
        source = self._source_for(
            namespace=namespace,
            node="",
            agent_name=self._subagent_for_namespace(namespace)
            or self._workflow_agent_name(node="", namespace=namespace),
        )
        if source is not None:
            return source.source_type in {"agent", "subagent"}
        return not self._workflow_mode and namespace == "root"

    @staticmethod
    def _cycle_key(namespace: str) -> str:
        return _namespace_scope(namespace)

    def _source_key(
        self,
        source: WorkflowEventSourceV1 | None,
        namespace: str,
        agent_name: str = "",
    ) -> str:
        if source is not None:
            return "|".join(
                (
                    source.source_type,
                    str(source.workflow_node_id),
                    str(source.agent_profile_id or ""),
                    str(source.subagent_profile_id or ""),
                )
            )
        if agent_name:
            return f"agent|{agent_name}"
        return f"unknown|{self._cycle_key(namespace)}"

    def _tool_cache_key(
        self,
        *,
        namespace: str,
        node: str,
        agent_name: str,
        call_id: str,
    ) -> tuple[str, str, str]:
        source = self._source_for(
            namespace=namespace,
            node=node,
            agent_name=agent_name,
        )
        return (
            self._source_key(source, namespace, agent_name),
            self._cycle_key(namespace),
            call_id,
        )

    def _event(
        self,
        event_type: str,
        phase: str,
        *,
        timestamp: str,
        namespace: str = "root",
        agent_name: str = "",
        node: str = "",
        message: str = "",
        data: object = None,
        stream_id: str = "",
        source: WorkflowEventSourceV1 | None = None,
        source_agent_name: str = "",
        source_type_override: str = "",
        workflow_event_kind: str = "",
        **values: str,
    ) -> OutputEvent:
        self._sequence += 1
        effective_agent_name = agent_name or self._main_agent_name
        effective_source = source or self._source_for(
            namespace=namespace,
            node=node,
            agent_name=source_agent_name or effective_agent_name,
        )
        effective_source_key = self._source_key(
            effective_source,
            namespace,
            "" if source_type_override else effective_agent_name,
        )
        return OutputEvent(
            event_type=event_type,
            phase=phase,
            sequence=self._sequence,
            timestamp=timestamp,
            namespace=namespace,
            agent_name=effective_agent_name,
            node=node,
            source_type=(
                source_type_override
                or (effective_source.source_type if effective_source else "agent")
            ),
            workflow_node_id=(
                effective_source.workflow_node_id if effective_source else ""
            ),
            agent_profile_id=(
                effective_source.agent_profile_id or "" if effective_source else ""
            ),
            subagent_profile_id=(
                effective_source.subagent_profile_id or "" if effective_source else ""
            ),
            message=message,
            data=data,
            values={key: str(value or "") for key, value in values.items()},
            stream_id=stream_id,
            raw_seq=self._raw_seq,
            source_key=effective_source_key,
            cycle_key=self._cycle_key(namespace),
            workflow_event_kind=workflow_event_kind,
        )

    def _source_for(
        self,
        *,
        namespace: str,
        node: str,
        agent_name: str,
    ) -> WorkflowEventSourceV1 | None:
        source = self._workflow_sources.get(node)
        if source is None:
            for part in reversed(namespace.split("/")):
                source = self._workflow_sources.get(part.partition(":")[0])
                if source is not None:
                    break
        if source is None:
            return None
        subagent_profile_id = self._workflow_subagent_profile_ids.get(
            source.workflow_node_id,
            self._subagent_profile_ids,
        ).get(agent_name)
        if not subagent_profile_id or agent_name in self._main_agent_names:
            return source
        return WorkflowEventSourceV1(
            source_type="subagent",
            workflow_node_id=source.workflow_node_id,
            agent_profile_id=source.agent_profile_id,
            subagent_profile_id=subagent_profile_id,
        )


__all__ = [
    "ModelCallBoundary",
    "OutputEvent",
    "WorkflowEventSourceV1",
    "MainAgentMediaBlock",
    "V3EventNormalizer",
]
