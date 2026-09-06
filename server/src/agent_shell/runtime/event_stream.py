from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.messages import AIMessage

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.event_origin import ResolvedEventOrigin
from agent_shell.runtime.media_events import MediaContentBlock
from agent_shell.runtime.message_state import MessageRunRegistry
from agent_shell.runtime.response_presentation import PresentationFrame
from agent_shell.runtime.usage import RunUsageAccumulator


@dataclass(slots=True)
class _MessageBlock:
    message_id: str
    block_type: str
    segment_end_text: str


@dataclass(frozen=True, slots=True)
class EventStreamProjection:
    frames: tuple[PresentationFrame, ...] = ()
    media: tuple[MediaContentBlock, ...] = ()


def _message_parts(data: object) -> tuple[object, Mapping[str, object]] | None:
    if isinstance(data, Mapping):
        metadata = data.get("metadata")
        return data, metadata if isinstance(metadata, Mapping) else {}
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return None
    metadata = data[1] if isinstance(data[1], Mapping) else {}
    return data[0], metadata


class RunEventStream:
    """Project one root Run's raw v3 events into presentation frames.

    The Event Output extension remains the only text/visibility owner. This
    class only recognizes official text/reasoning block boundaries, tracks
    usage and media, and suppresses the whole-message duplicate emitted after
    an already streamed message.
    """

    def __init__(self, usage: RunUsageAccumulator) -> None:
        self._usage = usage
        self._messages = MessageRunRegistry()
        self._blocks: dict[tuple[str, int], _MessageBlock] = {}
        self._frame_sequence = 0

    @staticmethod
    def is_streaming_start(envelope: Mapping[str, object]) -> bool:
        params = envelope.get("params")
        if str(envelope.get("method") or "") != "messages" or not isinstance(
            params, Mapping
        ):
            return False
        parts = _message_parts(params.get("data"))
        if parts is None or not isinstance(parts[0], Mapping):
            return False
        payload = parts[0]
        content = payload.get("content")
        return bool(
            payload.get("event") == "content-block-start"
            and isinstance(content, Mapping)
            and content.get("type") in {"text", "reasoning"}
        )

    def consume(
        self,
        envelope: Mapping[str, object],
        origin: ResolvedEventOrigin,
        *,
        text: str,
        segment_end_text: str = "",
    ) -> EventStreamProjection:
        params = envelope.get("params")
        if not isinstance(params, Mapping):
            return self._atomic_projection(text)
        if str(envelope.get("method") or "") != "messages":
            return self._atomic_projection(text)
        return self._message_projection(
            params.get("data"),
            origin,
            text=text,
            segment_end_text=segment_end_text,
        )

    def atomic(self, text: str) -> PresentationFrame:
        return self._frame("atomic", text)

    def close(self) -> None:
        self._blocks.clear()
        for run_key in self._messages.active_main_runs:
            self._messages.discard(run_key)

    def _message_projection(
        self,
        data: object,
        origin: ResolvedEventOrigin,
        *,
        text: str,
        segment_end_text: str,
    ) -> EventStreamProjection:
        parts = _message_parts(data)
        if parts is None:
            return self._atomic_projection(text)
        payload, metadata = parts
        run_id = str(metadata.get("run_id") or "")
        run_key = run_id or self._fallback_run_key(origin)

        if not isinstance(payload, Mapping):
            if not isinstance(payload, AIMessage):
                return self._atomic_projection(text)
            usage = payload.usage_metadata
            self._usage.merge(run_key, usage if isinstance(usage, Mapping) else {})
            if self._messages.was_streamed(run_key):
                return EventStreamProjection()
            media = tuple(self._whole_message_media(payload, run_key=run_key))
            return EventStreamProjection(
                frames=self._atomic_frames(text),
                media=media,
            )

        event_name = str(payload.get("event") or "")
        if event_name == "message-start":
            message_id = str(payload.get("id") or payload.get("message_id") or "")
            is_ai = str(payload.get("role") or "ai") in {"ai", "assistant"}
            self._messages.begin(
                run_key,
                message_id=message_id,
                main_agent_ai=origin.is_main_agent and is_ai,
                public_ai=origin.is_public_agent and is_ai,
            )
            return self._atomic_projection(text)

        if event_name == "message-finish":
            usage = payload.get("usage")
            self._usage.merge(run_key, usage if isinstance(usage, Mapping) else {})
            frames = self._close_message_blocks(run_key)
            frames.extend(self._atomic_frames(text))
            self._messages.discard(run_key)
            return EventStreamProjection(frames=tuple(frames))

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
            return self._atomic_projection(text)

        message = self._messages.get(run_key)
        public_ai = message.public_ai if message is not None else origin.is_public_agent
        index = payload.get("index")
        if not public_ai or not isinstance(index, int):
            return self._atomic_projection(text)
        key = (run_key, index)
        message_id = message.message_id if message is not None else ""
        block_id = f"{run_key}:{index}"

        if event_name == "content-block-start":
            content = payload.get("content")
            if not isinstance(content, Mapping):
                return self._atomic_projection(text)
            block_type = str(content.get("type") or "")
            if block_type not in {"text", "reasoning"}:
                return self._atomic_projection(text)
            self._blocks[key] = _MessageBlock(
                message_id=message_id,
                block_type=block_type,
                segment_end_text=segment_end_text,
            )
            return EventStreamProjection(
                frames=(
                    self._frame(
                        "start",
                        text,
                        block_id=block_id,
                        segment_end_text=segment_end_text,
                    ),
                )
            )

        if event_name == "content-block-delta":
            block = self._blocks.get(key)
            delta = payload.get("delta")
            if (
                block is None
                or not isinstance(delta, Mapping)
                or block.block_type not in {"text", "reasoning"}
            ):
                return self._atomic_projection(text)
            frames = (self._frame("delta", text, block_id=block_id),) if text else ()
            return EventStreamProjection(frames=frames)

        if event_name == "content-block-finish":
            content = payload.get("content")
            if not isinstance(content, Mapping):
                return self._atomic_projection(text)
            block = self._blocks.pop(key, None)
            content_type = str(content.get("type") or "")
            if block is not None and block.block_type in {"text", "reasoning"}:
                return EventStreamProjection(
                    frames=(
                        self._frame(
                            "finish",
                            text or block.segment_end_text,
                            block_id=block_id,
                        ),
                    )
                )
            if content_type in {"image", "audio", "video", "file"}:
                return EventStreamProjection(
                    frames=self._atomic_frames(text),
                    media=(
                        MediaContentBlock(
                            message_id=message_id,
                            block_index=index,
                            content=dict(content),
                            stream_id=block_id,
                        ),
                    ),
                )
            # A completed text/reasoning block without a preceding start is the
            # non-streaming form and is rendered in one atomic frame.
            return self._atomic_projection(text)

        return self._atomic_projection(text)

    def _whole_message_media(
        self,
        message: AIMessage,
        *,
        run_key: str,
    ) -> list[MediaContentBlock]:
        blocks = message.content_blocks
        if not isinstance(blocks, list):
            return []
        message_id = str(message.id or "")
        return [
            MediaContentBlock(
                message_id=message_id,
                block_index=index,
                content=dict(content),
                stream_id=f"{run_key}:{index}",
            )
            for index, content in enumerate(blocks)
            if isinstance(content, Mapping)
            and content.get("type") in {"image", "audio", "video", "file"}
        ]

    def _close_message_blocks(self, run_key: str) -> list[PresentationFrame]:
        frames: list[PresentationFrame] = []
        for key in tuple(key for key in self._blocks if key[0] == run_key):
            block = self._blocks.pop(key)
            frames.append(
                self._frame(
                    "finish",
                    block.segment_end_text,
                    block_id=f"{key[0]}:{key[1]}",
                )
            )
        return frames

    def _discard_message(self, run_key: str) -> None:
        for key in tuple(key for key in self._blocks if key[0] == run_key):
            self._blocks.pop(key, None)
        self._messages.discard(run_key)

    def _atomic_projection(self, text: str) -> EventStreamProjection:
        return EventStreamProjection(frames=self._atomic_frames(text))

    def _atomic_frames(self, text: str) -> tuple[PresentationFrame, ...]:
        return (self._frame("atomic", text),) if text else ()

    def _frame(
        self,
        phase: str,
        text: str,
        *,
        block_id: str = "",
        segment_end_text: str = "",
    ) -> PresentationFrame:
        self._frame_sequence += 1
        return PresentationFrame(
            phase=phase,  # type: ignore[arg-type]
            text=text,
            block_id=block_id,
            segment_end_text=segment_end_text,
            sequence=self._frame_sequence,
        )

    @staticmethod
    def _fallback_run_key(origin: ResolvedEventOrigin) -> str:
        return f"{origin.source_type}|{origin.subagent_profile_id}|{origin.namespace}"


__all__ = ["EventStreamProjection", "RunEventStream"]
