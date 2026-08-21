"""Small, product-owned stream transformer registrations.

The public output pipeline consumes the raw v3 event iterator.  LangGraph only
requests a stream mode when a registered transformer declares that it needs it,
so this module registers the ``custom`` mode without creating a second output
projection (or re-emitting custom events through a ``StreamChannel``).
"""

from __future__ import annotations

from typing import Any

from langgraph.stream import ProtocolEvent, StreamTransformer


class RawCustomEventTransformer(StreamTransformer):
    """Request custom events while preserving the raw event log exactly once.

    ``get_stream_writer()`` events are emitted on the raw ``custom`` channel.
    This transformer intentionally has no projection and never pushes a second
    event.  LangGraph creates one instance per mux scope (root and each child),
    so scoped child handling cannot duplicate events in the root iterator.
    """

    required_stream_modes = ("custom",)

    def init(self) -> dict[str, Any]:
        return {}

    def process(self, event: ProtocolEvent) -> bool:
        return True


__all__ = ["RawCustomEventTransformer"]
