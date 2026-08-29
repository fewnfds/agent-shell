from __future__ import annotations

from collections.abc import Mapping

from agent_shell.runtime.json_values import json_safe


def serialize_protocol_event(event: object) -> dict[str, object]:
    """Convert one root v3 ProtocolEvent envelope into persistent JSON data."""

    if not isinstance(event, Mapping):
        raise TypeError("the v3 protocol event must be a mapping")
    sequence = event.get("seq")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("the v3 protocol event must have a positive seq")
    method = event.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("the v3 protocol event must have a method")
    params = event.get("params")
    if not isinstance(params, Mapping):
        raise ValueError("the v3 protocol event must have params")

    serialized = json_safe(event)
    if not isinstance(serialized, dict):
        raise TypeError("the serialized v3 protocol event must be an object")
    return serialized


__all__ = ["serialize_protocol_event"]
