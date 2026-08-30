"""Publish only final assistant text from the Agent event stream.

Agent Event Output receives every raw LangGraph v3 ProtocolEvent. Returning an empty
string filters an event, so this example hides reasoning, tool activity,
Subagent progress, custom events, and lifecycle events. It is useful when an API
consumer should see only assistant-visible response text.

The ``event, origin`` mappings and ``output(event, origin) -> str`` signature
are owned by Agent Shell. No third-party dependency is required.
"""


def output(event, origin):
    """Return Main Agent response fragments and filter every other event."""

    if event.get("method") != "messages" or not origin.get("agent_profile_id"):
        return ""
    params = event.get("params")
    data = params.get("data") if isinstance(params, dict) else None
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return ""
    payload = data[0]
    if not isinstance(payload, dict):
        text = getattr(payload, "text", None)
        return text if isinstance(text, str) else ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta")
    if not isinstance(delta, dict):
        return ""
    return str(delta.get("text", ""))
