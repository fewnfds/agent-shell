"""Small v3 ProtocolEvent fixtures owned by Agent Shell's public dependencies.

These fixtures intentionally keep the official envelope and channel-specific
Python payload. They omit incidental LangGraph metadata that Agent Shell does
not consume. The shapes are locked to langgraph 1.2.11 / langchain 1.3.18 and
are checked against real public ``astream_events(version="v3")`` runs.
"""

from __future__ import annotations

from typing import cast

from langchain_core.messages import HumanMessage
from langgraph.stream import ProtocolEvent


def message_text_delta_event(
    *,
    seq: int = 4,
    model_run_id: str = "model-run-1",
    text: str = "h",
) -> ProtocolEvent:
    return cast(
        ProtocolEvent,
        {
            "type": "event",
            "method": "messages",
            "params": {
                "namespace": [],
                "timestamp": 1,
                "data": (
                    {
                        "event": "content-block-delta",
                        "index": 0,
                        "delta": {"type": "text-delta", "text": text},
                    },
                    {
                        "run_id": model_run_id,
                        "langgraph_node": "model",
                    },
                ),
            },
            "seq": seq,
        },
    )


def nested_custom_event(
    *,
    seq: int = 2,
    invocation_id: str = "node-invocation-1",
) -> ProtocolEvent:
    return cast(
        ProtocolEvent,
        {
            "type": "event",
            "method": "custom",
            "params": {
                "namespace": [f"child:{invocation_id}"],
                "timestamp": 1,
                "data": {"kind": "child-progress"},
            },
            "seq": seq,
        },
    )


def nested_lifecycle_started_event(
    *,
    seq: int = 1,
    invocation_id: str = "node-invocation-1",
) -> ProtocolEvent:
    namespace = [f"child:{invocation_id}"]
    return cast(
        ProtocolEvent,
        {
            "type": "event",
            "method": "lifecycle",
            "params": {
                "namespace": [],
                "timestamp": 1,
                "data": {
                    "event": "started",
                    "namespace": namespace,
                    "graph_name": "child",
                    "trigger_call_id": invocation_id,
                },
            },
            "seq": seq,
        },
    )


def values_with_message_event(*, seq: int = 1) -> ProtocolEvent:
    return cast(
        ProtocolEvent,
        {
            "type": "event",
            "method": "values",
            "params": {
                "namespace": [],
                "timestamp": 1,
                "data": {"messages": [HumanMessage(content="hi", id="human-1")]},
                "interrupts": (),
            },
            "seq": seq,
        },
    )


__all__ = [
    "message_text_delta_event",
    "nested_custom_event",
    "nested_lifecycle_started_event",
    "values_with_message_event",
]
