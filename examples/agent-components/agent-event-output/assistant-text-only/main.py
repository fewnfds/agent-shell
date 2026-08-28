"""Publish only final assistant text from the Agent event stream.

Agent Event Output receives every normalized Agent event. Returning an empty
string filters an event, so this example hides reasoning, tool activity,
Subagent progress, custom events, and lifecycle events. It is useful when an API
consumer should see only assistant-visible response text.

The ``event`` mapping and ``output(event) -> str`` signature are owned by Agent
Shell. No third-party dependency is required.
"""


def output(event):
    """Return Main Agent response fragments and filter every other event."""

    if (
        event["event_type"] != "assistant_text"
        or event["source_type"] != "agent"
    ):
        return ""
    if isinstance(event["data"], dict) and event["data"].get("type") in {
        "image", "audio", "video", "file",
    }:
        return event["message"]
    return event["message"] if event["phase"] == "delta" else ""
