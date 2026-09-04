from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from langchain_core.messages import AIMessage

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.event_origin import ResolvedEventOrigin
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.message_state import MessageRunRegistry
from agent_shell.runtime.response_presentation import (
    ResponseEvent,
    ResponseModelCallBoundary,
)
from agent_shell.runtime.usage import RunUsageAccumulator


@dataclass(slots=True)
class _MessageBlock:
    message_id: str
    block_type: str
    origin: ResolvedEventOrigin


def _message_text(message: object) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "text"
        )
    return str(content) if content is not None else ""


def _message_parts(data: object) -> tuple[object, Mapping[str, object]] | None:
    if isinstance(data, Mapping):
        metadata = data.get("metadata")
        return data, metadata if isinstance(metadata, Mapping) else {}
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return None
    metadata = data[1] if isinstance(data[1], Mapping) else {}
    return data[0], metadata


class RunEventStream:
    """Consume raw v3 channels into Run state and scheduler-private signals."""

    def __init__(
        self,
        usage: RunUsageAccumulator,
    ) -> None:
        self._usage = usage
        self._messages = MessageRunRegistry()
        self._blocks: dict[tuple[str, int], _MessageBlock] = {}
        self._signal_sequence = 0

    def consume(
        self,
        envelope: Mapping[str, object],
        origin: ResolvedEventOrigin,
    ) -> tuple[
        tuple[ResponseEvent | ResponseModelCallBoundary | MediaContentBlock, ...],
        bool,
    ]:
        """Return private signals and whether projected raw text stays visible."""

        params = envelope.get("params")
        if not isinstance(params, Mapping):
            return (), True
        method = str(envelope.get("method") or "")
        data = params.get("data")
        raw_seq = envelope.get("seq")
        raw_seq = raw_seq if isinstance(raw_seq, int) and raw_seq >= 0 else 0
        if method == "messages":
            suppress_output = self._is_streamed_whole_message(data, origin)
            return (
                tuple(self._message_events(data, raw_seq=raw_seq, origin=origin)),
                not suppress_output,
            )
        if method == "tools":
            return tuple(self._tool_events(data, origin=origin)), True
        if method == "lifecycle":
            return tuple(self._lifecycle_events(data, origin=origin)), True
        return (), True

    def close(self) -> None:
        run_keys = self._messages.active_main_runs | {key[0] for key in self._blocks}
        for run_key in tuple(run_keys):
            self._discard_message(run_key)

    def media_notification(
        self,
        origin: ResolvedEventOrigin,
        block: MediaContentBlock,
    ) -> ResponseEvent:
        return self._signal(
            origin,
            kind="content",
            phase="end",
            data=block.content,
            stream_id=block.stream_id,
        )

    def atomic(self, origin: ResolvedEventOrigin, data: object) -> ResponseEvent:
        return self._signal(origin, kind="event", phase="end", data=data)

    def _message_events(
        self,
        data: object,
        *,
        raw_seq: int,
        origin: ResolvedEventOrigin,
    ) -> list[ResponseEvent | ResponseModelCallBoundary | MediaContentBlock]:
        parts = _message_parts(data)
        if parts is None:
            return []
        payload, metadata = parts
        run_id = str(metadata.get("run_id") or "")
        run_key = run_id or self._fallback_run_key(origin)

        if not isinstance(payload, Mapping):
            if not isinstance(payload, AIMessage):
                return []
            usage = payload.usage_metadata
            usage_data = usage if isinstance(usage, Mapping) else {}
            self._usage.merge(run_key, usage_data)
            if not origin.is_public_agent:
                return []
            boundary = self._boundary(origin, run_key, raw_seq=raw_seq)
            if self._messages.was_streamed(run_key):
                return [boundary, replace(boundary, phase="end")]
            blocks = payload.content_blocks
            if not isinstance(blocks, list):
                text = _message_text(payload)
                blocks = [{"type": "text", "text": text}] if text else []
            events: list[
                ResponseEvent | ResponseModelCallBoundary | MediaContentBlock
            ] = [boundary]
            message_id = str(payload.id or "")
            for index, content in enumerate(blocks):
                if isinstance(content, Mapping):
                    events.extend(
                        self._finished_block(
                            dict(content),
                            message_id=message_id,
                            block_index=index,
                            stream_id=f"{run_key}:{index}",
                            origin=origin,
                        )
                    )
            events.append(replace(boundary, phase="end"))
            return events

        event_name = str(payload.get("event") or "")
        if event_name == "message-start":
            message_id = str(payload.get("id") or payload.get("message_id") or "")
            is_ai = str(payload.get("role") or "ai") == "ai"
            self._messages.begin(
                run_key,
                message_id=message_id,
                main_agent_ai=origin.is_main_agent and is_ai,
                public_ai=origin.is_public_agent and is_ai,
            )
            return [self._boundary(origin, run_key, raw_seq=raw_seq)] if (
                origin.is_public_agent and is_ai
            ) else []
        if event_name == "message-finish":
            usage = payload.get("usage")
            self._usage.merge(run_key, usage if isinstance(usage, Mapping) else {})
            message = self._messages.get(run_key)
            is_public = message.public_ai if message is not None else origin.is_public_agent
            self._discard_message(run_key)
            return [
                self._boundary(origin, run_key, raw_seq=raw_seq, phase="end")
            ] if is_public else []
        if event_name == "error":
            message = self._messages.get(run_key)
            is_main = message.main_agent_ai if message is not None else origin.is_main_agent
            self._discard_message(run_key)
            if is_main:
                raise AgentRuntimeError(
                    "agent_execution_failed",
                    "The model response stream failed.",
                    status_code=502,
                )
            return []

        message = self._messages.get(run_key)
        if not (message.public_ai if message is not None else origin.is_public_agent):
            return []
        index = payload.get("index")
        if not isinstance(index, int):
            return []
        key = (run_key, index)
        message_id = message.message_id if message is not None else ""
        stream_id = f"{run_key}:{index}"

        if event_name == "content-block-start":
            content = payload.get("content")
            if not isinstance(content, Mapping):
                return []
            block_type = str(content.get("type") or "")
            self._blocks[key] = _MessageBlock(
                message_id=message_id,
                block_type=block_type,
                origin=origin,
            )
            if block_type in {"text", "reasoning"}:
                return [
                    self._signal(
                        origin,
                        kind="content",
                        phase="start",
                        data=content,
                        stream_id=stream_id,
                    )
                ]
            if block_type in {
                "tool_call",
                "server_tool_call",
                "tool_call_chunk",
                "server_tool_call_chunk",
            }:
                return [
                    self._tool_call(
                        dict(content),
                        phase="start",
                        stream_id=stream_id,
                        origin=origin,
                    )
                ]
            return []
        if event_name == "content-block-delta":
            block = self._blocks.get(key)
            delta = payload.get("delta")
            if (
                block is None
                or not isinstance(delta, Mapping)
                or block.block_type not in {"text", "reasoning"}
            ):
                return []
            return [
                self._signal(
                    block.origin,
                    kind="content",
                    phase="delta",
                    data=delta,
                    stream_id=stream_id,
                )
            ]
        if event_name == "content-block-finish":
            content = payload.get("content")
            if not isinstance(content, Mapping):
                return []
            block = self._blocks.pop(key, None)
            return self._finished_block(
                dict(content),
                message_id=(block.message_id if block is not None else message_id),
                block_index=index,
                stream_id=stream_id,
                origin=(block.origin if block is not None else origin),
                started_type=(block.block_type if block is not None else ""),
            )
        return []

    def _finished_block(
        self,
        content: dict[str, object],
        *,
        message_id: str,
        block_index: int,
        stream_id: str,
        origin: ResolvedEventOrigin,
        started_type: str = "",
    ) -> list[ResponseEvent | MediaContentBlock]:
        block_type = started_type or str(content.get("type") or "")
        final_type = str(content.get("type") or "")
        if block_type in {"text", "reasoning"}:
            return [
                self._signal(
                    origin,
                    kind="content",
                    phase="end",
                    data=content,
                    stream_id=stream_id,
                )
            ]
        if final_type in {"image", "audio", "video", "file"}:
            return [
                MediaContentBlock(
                    message_id=message_id,
                    block_index=block_index,
                    content=content,
                    stream_id=stream_id,
                )
            ]
        if final_type in {"tool_call", "server_tool_call"}:
            return [
                self._tool_call(
                    content,
                    phase="end",
                    stream_id=stream_id,
                    origin=origin,
                )
            ]
        call_id = str(content.get("id") or content.get("tool_call_id") or "")
        if final_type in {
            "tool_call_chunk",
            "server_tool_call_chunk",
            "invalid_tool_call",
        }:
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase="error",
                    data=content,
                    stream_id=stream_id,
                    tool_kind="error",
                    tool_call_id=call_id,
                )
            ]
        if final_type == "server_tool_result":
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase=("error" if str(content.get("status") or "") == "error" else "end"),
                    data=content.get("output"),
                    stream_id=stream_id,
                    tool_kind=("error" if str(content.get("status") or "") == "error" else "result"),
                    tool_call_id=call_id,
                )
            ]
        return []

    def _tool_call(
        self,
        content: dict[str, object],
        *,
        phase: str,
        stream_id: str,
        origin: ResolvedEventOrigin,
    ) -> ResponseEvent:
        call_id = str(content.get("id") or "")
        return self._signal(
            origin,
            kind="tool",
            phase=phase,
            data=content,
            stream_id=stream_id,
            tool_kind="call",
            tool_call_id=call_id,
        )

    def _tool_events(
        self,
        data: object,
        *,
        origin: ResolvedEventOrigin,
    ) -> list[ResponseEvent]:
        if not isinstance(data, Mapping) or not origin.is_public_agent:
            return []
        lifecycle = str(data.get("event") or "")
        call_id = str(data.get("tool_call_id") or "")
        if lifecycle == "tool-started":
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase="start",
                    data=data,
                    tool_kind="progress",
                    tool_call_id=call_id,
                )
            ]
        if lifecycle == "tool-output-delta":
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase="delta",
                    data=data,
                    tool_kind="progress",
                    tool_call_id=call_id,
                )
            ]
        if lifecycle == "tool-finished":
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase="end",
                    data=data.get("output"),
                    tool_kind="result",
                    tool_call_id=call_id,
                )
            ]
        if "fail" in lifecycle or "error" in lifecycle:
            return [
                self._signal(
                    origin,
                    kind="tool",
                    phase="error",
                    data=None,
                    tool_kind="error",
                    tool_call_id=call_id,
                )
            ]
        return []

    def _lifecycle_events(
        self,
        data: object,
        *,
        origin: ResolvedEventOrigin,
    ) -> list[ResponseEvent]:
        if not isinstance(data, Mapping):
            return []
        status = str(data.get("event") or "running")
        phase = (
            "start"
            if status == "started"
            else "error"
            if status in {
                "failed",
                "error",
                "interrupted",
                "cancelled",
                "timeout",
                "timed_out",
            }
            else "end"
        )
        is_node_lifecycle = origin.source_type in {"agent", "script"}
        return [
            self._signal(
                origin,
                kind=("lifecycle" if is_node_lifecycle else "event"),
                phase=phase,
                data=data,
                terminal=(
                    is_node_lifecycle
                    and bool(origin.workflow_node_id)
                    and phase in {"end", "error"}
                ),
            )
        ]

    def _signal(
        self,
        origin: ResolvedEventOrigin,
        *,
        kind: str,
        phase: str,
        data: object = None,
        stream_id: str = "",
        tool_kind: str = "",
        tool_call_id: str = "",
        terminal: bool = False,
    ) -> ResponseEvent:
        self._signal_sequence += 1
        return ResponseEvent(
            kind=kind,  # type: ignore[arg-type]
            phase=phase,
            sequence=self._signal_sequence,
            namespace=origin.namespace,
            source_type=origin.source_type,
            workflow_node_id=origin.workflow_node_id,
            agent_profile_id=origin.agent_profile_id,
            subagent_profile_id=origin.subagent_profile_id,
            data=data,
            stream_id=stream_id,
            cycle_key=origin.cycle_key,
            tool_kind=tool_kind,  # type: ignore[arg-type]
            tool_call_id=tool_call_id,
            terminal=terminal,
        )

    @staticmethod
    def _boundary(
        origin: ResolvedEventOrigin,
        run_key: str,
        *,
        raw_seq: int,
        phase: str = "start",
    ) -> ResponseModelCallBoundary:
        return ResponseModelCallBoundary(
            run_key=run_key,
            source_type=origin.source_type,
            workflow_node_id=origin.workflow_node_id,
            agent_profile_id=origin.agent_profile_id,
            subagent_profile_id=origin.subagent_profile_id,
            cycle_key=origin.cycle_key,
            raw_seq=raw_seq,
            phase="end" if phase == "end" else "start",
        )

    @staticmethod
    def _fallback_run_key(origin: ResolvedEventOrigin) -> str:
        return "|".join((*origin.correlation_source, origin.cycle_key))

    def _discard_message(self, run_key: str) -> None:
        for key in tuple(key for key in self._blocks if key[0] == run_key):
            self._blocks.pop(key, None)
        self._messages.discard(run_key)

    def _is_streamed_whole_message(
        self,
        data: object,
        origin: ResolvedEventOrigin,
    ) -> bool:
        parts = _message_parts(data)
        if parts is None:
            return False
        payload, metadata = parts
        if isinstance(payload, Mapping) or not isinstance(payload, AIMessage):
            return False
        run_id = str(metadata.get("run_id") or "")
        run_key = run_id or self._fallback_run_key(origin)
        return self._messages.was_streamed(run_key)


__all__ = ["RunEventStream"]
