from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

_FINISH_REASON_FIELDS = (
    "finish_reason",
    "stop_reason",
    "native_finish_reason",
)


def extract_provider_finish_reason(
    metadata: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return the Provider value and its exact metadata field without guessing."""

    for field_name in _FINISH_REASON_FIELDS:
        value = metadata.get(field_name)
        if isinstance(value, str) and value:
            return value, f"response_metadata.{field_name}"
    return None, None


def finish_reason_category(reason: str | None) -> str:
    normalized = (reason or "").strip().lower()
    if normalized in {"stop", "end_turn", "completed", "complete"}:
        return "stop"
    if normalized in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "model_length",
    }:
        return "length"
    if normalized in {"content_filter", "safety", "blocked"}:
        return "content_filter"
    if normalized in {"tool_calls", "function_call"}:
        return "tool_calls"
    if normalized == "error":
        return "error"
    return "unknown"


def public_finish_reason(reason: str | None) -> str:
    """Expose the Provider value when present and an explicit unknown otherwise."""

    return reason or "unknown"


def termination_block(
    reason: str | None,
    source: str | None,
) -> dict[str, object] | None:
    category = finish_reason_category(reason)
    if category == "stop":
        return None
    messages = {
        "length": "The provider ended generation because its output limit was reached.",
        "content_filter": "The provider ended generation because content filtering was applied.",
        "tool_calls": "The agent ended while the provider was requesting tool calls.",
        "error": "The provider reported an error termination.",
        "unknown": "The provider did not report a recognized completion reason.",
    }
    return {
        "status": "incomplete",
        "finish_reason": public_finish_reason(reason),
        "category": category,
        "source": source,
        "message": messages[category],
    }


@dataclass(frozen=True, slots=True)
class ModelResponse:
    timestamp: str
    namespace: str
    agent_name: str
    node: str
    run_id: str
    message_id: str
    is_main_agent: bool
    usage: dict[str, Any] = field(default_factory=dict)
    start_metadata: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    stream_diagnostics: dict[str, Any] = field(default_factory=dict)
    provider_finish_reason: str | None = None
    finish_reason_source: str | None = None

    def timeline_data(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "node": self.node,
            "run_id": self.run_id,
            "message_id": self.message_id,
            "is_main_agent": self.is_main_agent,
            "provider_finish_reason": self.provider_finish_reason,
            "finish_reason_source": self.finish_reason_source,
            "finish_reason_category": finish_reason_category(
                self.provider_finish_reason
            ),
            "usage": self.usage,
            "start_metadata": self.start_metadata,
            "response_metadata": self.response_metadata,
            "additional_kwargs": self.additional_kwargs,
            "content_blocks": self.content_blocks,
            "stream_diagnostics": self.stream_diagnostics,
        }


class ModelResponseTracker:
    """Collect response-only state without coupling it to output templates."""

    def __init__(
        self, observers: tuple[Callable[[ModelResponse], None], ...] = ()
    ) -> None:
        self._observers = observers
        self._start_metadata: dict[str, dict[str, object]] = {}
        self._stream_diagnostics: dict[str, dict[str, int]] = {}
        self._content_blocks: dict[str, dict[int, dict[str, object]]] = {}
        self.last_main_agent_finish_reason: str | None = None
        self.last_main_agent_finish_reason_source: str | None = None
        self.last_main_agent_response: ModelResponse | None = None

    def begin(self, run_key: str, metadata: object) -> None:
        self._start_metadata[run_key] = (
            dict(metadata) if isinstance(metadata, dict) else {}
        )
        self._stream_diagnostics[run_key] = {
            "content_block_count": 0,
            "delta_block_count": 0,
            "snapshot_mismatch_count": 0,
            "block_type_mismatch_count": 0,
            "incomplete_block_count": 0,
        }
        self._content_blocks[run_key] = {}

    def finish_block(
        self, run_key: str, index: int, content: dict[str, object]
    ) -> None:
        self._content_blocks.setdefault(run_key, {})[index] = dict(content)

    def diagnostics(self, run_key: str) -> dict[str, int]:
        return self._stream_diagnostics.setdefault(run_key, {})

    def discard(self, run_key: str) -> None:
        self._start_metadata.pop(run_key, None)
        self._stream_diagnostics.pop(run_key, None)
        self._content_blocks.pop(run_key, None)

    def record(
        self,
        *,
        timestamp: str,
        namespace: str,
        agent_name: str,
        node: str,
        run_id: str,
        run_key: str,
        message_id: str,
        is_main_agent: bool,
        usage: dict[str, object],
        response_metadata: dict[str, object],
        additional_kwargs: dict[str, object],
        content_blocks: list[dict[str, object]] | None = None,
    ) -> None:
        reason, source = extract_provider_finish_reason(response_metadata)
        if is_main_agent:
            self.last_main_agent_finish_reason = reason
            self.last_main_agent_finish_reason_source = source
        response = ModelResponse(
            timestamp=timestamp,
            namespace=namespace,
            agent_name=agent_name,
            node=node,
            run_id=run_id,
            message_id=message_id,
            is_main_agent=is_main_agent,
            usage=dict(usage),
            start_metadata=dict(self._start_metadata.get(run_key, {})),
            response_metadata=dict(response_metadata),
            additional_kwargs=dict(additional_kwargs),
            content_blocks=(
                [dict(block) for block in content_blocks]
                if content_blocks is not None
                else [
                    dict(block)
                    for _, block in sorted(
                        self._content_blocks.get(run_key, {}).items()
                    )
                ]
            ),
            stream_diagnostics=dict(self._stream_diagnostics.get(run_key, {})),
            provider_finish_reason=reason,
            finish_reason_source=source,
        )
        if is_main_agent:
            self.last_main_agent_response = deepcopy(response)
        for observer in self._observers:
            observer(response)
