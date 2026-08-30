"""Publish concise Workflow lifecycle and custom progress events.

This example demonstrates event filtering for Workflow Event Output. Lifecycle
status is handled by ``run_output``; ``get_stream_writer()`` calls made by
Command code arrive as ``custom`` events with their raw payload.
All State snapshots, task records, checkpoints, debug data, and other event
types are filtered by returning an empty string.

The example is useful for a compact progress feed and requires no third-party
dependency.
"""


def output(event, origin):
    """Render progress lines and filter non-progress Workflow events."""

    if event.get("method") == "custom":
        params = event.get("params")
        data = params.get("data") if isinstance(params, dict) else ""
        return f"Workflow progress: {data}\n"
    return ""


def run_output(event, origin):
    if event.get("type") == "agent_shell.workflow_run":
        return f'Workflow {event.get("status", "")}\n'
    return ""
