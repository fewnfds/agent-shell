"""Publish concise Workflow lifecycle and custom progress events.

This example demonstrates event filtering for Workflow Event Output. Lifecycle
events show run status, while ``get_stream_writer()`` calls made by Command
code arrive as ``custom`` events with their channel and message.
All State snapshots, task records, checkpoints, debug data, and other event
types are filtered by returning an empty string.

The example is useful for a compact progress feed and requires no third-party
dependency.
"""


def output(event):
    """Render progress lines and filter non-progress Workflow events."""

    event_type = event["event_type"]
    if event_type == "lifecycle":
        return f'Workflow {event["status"]}: {event["message"]}\n'
    if event_type == "custom":
        return f'Workflow progress [{event["channel"]}]: {event["message"]}\n'
    return ""
