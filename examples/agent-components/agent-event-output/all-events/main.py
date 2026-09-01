"""Render every currently exposed Agent event as readable HTML.

Assistant text and reasoning are the only streamed event families. Their
opening markup comes from ``output`` on ``content-block-start``; deltas append
message text; their normal closing markup comes from ``output`` on
``content-block-finish``. ``segment_end`` supplies the same kind of optional
suffix when the response scheduler has to end a presentation segment early.

Every other event renderer returns one complete, self-contained ``details``
element. Tool-call fragments are intentionally filtered until the complete
call arrives, so a declaration and its terminal Tool result remain atomic.
"""

import json
from collections.abc import Mapping
from html import escape


_SCOPE = "Agent"
_MESSAGE_STYLE = "white-space:pre-wrap;margin:0.4rem 0 0.35rem"
_META_STYLE = "color:#6c757d;font-size:0.78em;line-height:1.35"


def _params(event):
    value = event.get("params")
    return value if isinstance(value, Mapping) else {}


def _message_parts(event):
    data = _params(event).get("data")
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return None, {}
    metadata = data[1] if isinstance(data[1], Mapping) else {}
    return data[0], metadata


def _json_text(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


def _metadata(event, origin, event_name, payload=None, message_metadata=None):
    params = _params(event)
    message_metadata = message_metadata or {}
    subject = payload if isinstance(payload, Mapping) else {}
    nested = subject.get("content") or subject.get("delta")
    nested = nested if isinstance(nested, Mapping) else subject
    namespace = params.get("namespace")
    if isinstance(namespace, (list, tuple)):
        namespace = "/".join(str(part) for part in namespace) or "root"

    pairs = [
        ("protocol_type", event.get("type")),
        ("event_id", event.get("event_id")),
        ("method", event.get("method")),
        ("event", event_name),
        ("seq", event.get("seq")),
        ("namespace", namespace),
        ("timestamp", params.get("timestamp")),
        ("run_id", message_metadata.get("run_id")),
        ("langgraph_node", message_metadata.get("langgraph_node")),
        ("langgraph_step", message_metadata.get("langgraph_step")),
        (
            "langgraph_checkpoint_ns",
            message_metadata.get("langgraph_checkpoint_ns"),
        ),
        ("lc_agent_name", message_metadata.get("lc_agent_name")),
        ("ls_provider", message_metadata.get("ls_provider")),
        ("ls_model_name", message_metadata.get("ls_model_name")),
        ("message_id", subject.get("id") or subject.get("message_id")),
        ("block_index", subject.get("index")),
        ("content_type", nested.get("type")),
        (
            "tool_call_id",
            nested.get("tool_call_id")
            or nested.get("id")
            or subject.get("tool_call_id"),
        ),
        ("tool_name", nested.get("name") or subject.get("name")),
        ("lifecycle_id", origin.get("lifecycle_id")),
        ("workflow_run_id", origin.get("workflow_run_id")),
        ("parent_workflow_run_id", origin.get("parent_workflow_run_id")),
        ("workflow_id", origin.get("workflow_id")),
        ("workflow_role", origin.get("workflow_role")),
        ("background_task_id", origin.get("background_task_id")),
        ("run_depth", origin.get("run_depth")),
        ("workflow_node_id", origin.get("workflow_node_id")),
        ("node_invocation_id", origin.get("node_invocation_id")),
        ("agent_profile_id", origin.get("agent_profile_id")),
        ("subagent_profile_id", origin.get("subagent_profile_id")),
    ]
    rendered = []
    for key, value in pairs:
        if value is None or value == "" or value == [] or value == ():
            continue
        rendered.append(f"{key}={escape(str(value), quote=True)}")
    return " | ".join(rendered)


def _atomic(title, value, event, origin, event_name, payload=None, metadata=None):
    meta = _metadata(event, origin, event_name, payload, metadata)
    return (
        f'<details open><summary>{escape(_SCOPE + " · " + title)}</summary>\n'
        f'<pre style="{_MESSAGE_STYLE}">{escape(_json_text(value))}</pre>\n'
        f'<div><small style="{_META_STYLE}">{meta}</small></div>\n'
        "</details>\n"
    )


def _stream_start(title):
    return (
        f'<details open><summary>{escape(_SCOPE + " · " + title)}</summary>\n'
        f'<div style="{_MESSAGE_STYLE}">'
    )


def _stream_end(event, origin, event_name, payload, metadata):
    meta = _metadata(event, origin, event_name, payload, metadata)
    return (
        "</div>\n"
        f'<div><small style="{_META_STYLE}">{meta}</small></div>\n'
        "</details>\n"
    )


def render_message_start(event, origin, payload, metadata):
    """A model message invocation has started."""

    return _atomic("Message started", payload, event, origin, "message-start", payload, metadata)


def render_assistant_text_start(event, origin, payload, metadata):
    """Open one streamed assistant-text presentation segment."""

    return _stream_start("Assistant text")


def render_assistant_text_delta(event, origin, payload, metadata):
    """Append one assistant-text token fragment."""

    delta = payload.get("delta")
    return escape(str(delta.get("text", ""))) if isinstance(delta, Mapping) else ""


def render_assistant_text_end(event, origin, payload, metadata):
    """Close a normally completed assistant-text block."""

    return _stream_end(event, origin, "content-block-finish", payload, metadata)


def render_assistant_text_segment_end(event, origin, payload, metadata):
    """Close a scheduler presentation segment without inventing an event."""

    return _stream_end(event, origin, "presentation-segment-end", payload, metadata)


def render_reasoning_start(event, origin, payload, metadata):
    """Open one streamed model-reasoning presentation segment."""

    return _stream_start("Reasoning")


def render_reasoning_delta(event, origin, payload, metadata):
    """Append one model-reasoning token fragment."""

    delta = payload.get("delta")
    return escape(str(delta.get("reasoning", ""))) if isinstance(delta, Mapping) else ""


def render_reasoning_end(event, origin, payload, metadata):
    """Close a normally completed model-reasoning block."""

    return _stream_end(event, origin, "content-block-finish", payload, metadata)


def render_reasoning_segment_end(event, origin, payload, metadata):
    """Close a reasoning presentation segment released by the scheduler."""

    return _stream_end(event, origin, "presentation-segment-end", payload, metadata)


def render_tool_call_fragment(event, origin, payload, metadata):
    """Filter incomplete Tool-call chunks until the finalized call arrives."""

    return ""


def render_tool_call(event, origin, payload, metadata):
    """A complete model Tool-call declaration."""

    return _atomic(
        "Tool call", payload.get("content"), event, origin, "tool-call", payload, metadata
    )


def render_media_content(event, origin, payload, metadata):
    """A complete image, audio, video, or file content block."""

    return _atomic(
        "Media content",
        payload.get("content"),
        event,
        origin,
        "media-content",
        payload,
        metadata,
    )


def render_other_content(event, origin, payload, metadata):
    """A complete future or provider-specific content-block event."""

    return _atomic(
        "Other content",
        payload,
        event,
        origin,
        str(payload.get("event") or "content"),
        payload,
        metadata,
    )


def render_message_finish(event, origin, payload, metadata):
    """The model message invocation finished, including usage when supplied."""

    return _atomic("Message finished", payload, event, origin, "message-finish", payload, metadata)


def render_message_error(event, origin, payload, metadata):
    """The model message invocation failed."""

    return _atomic("Message error", payload, event, origin, "message-error", payload, metadata)


def render_ai_message_snapshot(event, origin, message, metadata):
    """A complete AIMessage snapshot for a non-incremental model response."""

    return _atomic(
        "AIMessage snapshot",
        message,
        event,
        origin,
        "ai-message-snapshot",
        None,
        metadata,
    )


def render_tool_started(event, origin, data):
    """A Tool execution began with its complete input metadata."""

    return _atomic("Tool started", data, event, origin, "tool-started", data)


def render_tool_output_delta(event, origin, data):
    """A complete Tool progress event; the Tool result itself is not streamed."""

    return _atomic("Tool progress", data, event, origin, "tool-output-delta", data)


def render_tool_finished(event, origin, data):
    """A complete terminal Tool result."""

    return _atomic("Tool result", data, event, origin, "tool-finished", data)


def render_tool_error(event, origin, data):
    """A complete terminal Tool failure."""

    return _atomic("Tool error", data, event, origin, str(data.get("event") or "tool-error"), data)


def render_lifecycle_started(event, origin, data):
    """A nested graph or Agent lifecycle began."""

    return _atomic("Lifecycle started", data, event, origin, "lifecycle-started", data)


def render_lifecycle_finished(event, origin, data):
    """A nested graph or Agent lifecycle completed."""

    return _atomic("Lifecycle finished", data, event, origin, "lifecycle-finished", data)


def render_lifecycle_error(event, origin, data):
    """A nested graph or Agent lifecycle ended unsuccessfully."""

    return _atomic(
        "Lifecycle error",
        data,
        event,
        origin,
        str(data.get("event") or "lifecycle-error"),
        data,
    )


def render_values(event, origin, data):
    """A complete graph State snapshot from the values channel."""

    return _atomic("State values", data, event, origin, "values")


def render_custom(event, origin, data):
    """One complete application-defined get_stream_writer payload."""

    return _atomic("Custom event", data, event, origin, "custom")


def render_unknown_event(event, origin):
    """A complete future channel event kept visible for debugging."""

    return _atomic(
        "Unknown event",
        _params(event).get("data"),
        event,
        origin,
        str(event.get("method") or "unknown"),
    )


def output(event, origin):
    """Flat dispatcher: invoke exactly one renderer for each raw event."""

    method = str(event.get("method") or "")
    if method == "messages":
        payload, metadata = _message_parts(event)
        if not isinstance(payload, Mapping):
            return render_ai_message_snapshot(event, origin, payload, metadata)
        event_name = str(payload.get("event") or "")
        content = payload.get("content")
        delta = payload.get("delta")
        block = content if isinstance(content, Mapping) else delta
        block = block if isinstance(block, Mapping) else {}
        block_type = str(block.get("type") or "")
        if event_name == "message-start":
            return render_message_start(event, origin, payload, metadata)
        if event_name == "content-block-start" and block_type == "text":
            return render_assistant_text_start(event, origin, payload, metadata)
        if event_name == "content-block-delta" and block_type == "text-delta":
            return render_assistant_text_delta(event, origin, payload, metadata)
        if event_name == "content-block-finish" and block_type == "text":
            return render_assistant_text_end(event, origin, payload, metadata)
        if event_name == "content-block-start" and block_type == "reasoning":
            return render_reasoning_start(event, origin, payload, metadata)
        if event_name == "content-block-delta" and block_type == "reasoning-delta":
            return render_reasoning_delta(event, origin, payload, metadata)
        if event_name in {"content-block-start", "content-block-delta"} and block_type in {
            "tool_call",
            "server_tool_call",
            "tool_call_chunk",
            "server_tool_call_chunk",
        }:
            return render_tool_call_fragment(event, origin, payload, metadata)
        if event_name == "content-block-finish" and block_type == "reasoning":
            return render_reasoning_end(event, origin, payload, metadata)
        if event_name == "content-block-finish" and block_type in {"tool_call", "server_tool_call"}:
            return render_tool_call(event, origin, payload, metadata)
        if event_name == "content-block-finish" and block_type in {
            "image",
            "audio",
            "video",
            "file",
        }:
            return render_media_content(event, origin, payload, metadata)
        if event_name in {"content-block-start", "content-block-delta", "content-block-finish"}:
            return render_other_content(event, origin, payload, metadata)
        if event_name == "message-finish":
            return render_message_finish(event, origin, payload, metadata)
        if event_name == "error":
            return render_message_error(event, origin, payload, metadata)
        return render_unknown_event(event, origin)

    data = _params(event).get("data")
    if method == "tools" and isinstance(data, Mapping):
        tool_event = str(data.get("event") or "")
        if tool_event == "tool-started":
            return render_tool_started(event, origin, data)
        if tool_event == "tool-output-delta":
            return render_tool_output_delta(event, origin, data)
        if tool_event == "tool-finished":
            return render_tool_finished(event, origin, data)
        return render_tool_error(event, origin, data)
    if method == "lifecycle" and isinstance(data, Mapping):
        lifecycle_event = str(data.get("event") or "")
        if lifecycle_event == "started":
            return render_lifecycle_started(event, origin, data)
        if lifecycle_event in {
            "failed",
            "error",
            "interrupted",
            "cancelled",
            "timeout",
            "timed_out",
        }:
            return render_lifecycle_error(event, origin, data)
        return render_lifecycle_finished(event, origin, data)
    if method == "values":
        return render_values(event, origin, data)
    if method == "custom":
        return render_custom(event, origin, data)
    return render_unknown_event(event, origin)


def segment_end(event, origin):
    """Return an optional suffix for text/reasoning presentation boundaries."""

    payload, metadata = _message_parts(event)
    if not isinstance(payload, Mapping) or payload.get("event") != "content-block-start":
        return ""
    content = payload.get("content")
    block_type = str(content.get("type") or "") if isinstance(content, Mapping) else ""
    if block_type == "text":
        return render_assistant_text_segment_end(event, origin, payload, metadata)
    if block_type == "reasoning":
        return render_reasoning_segment_end(event, origin, payload, metadata)
    return ""
