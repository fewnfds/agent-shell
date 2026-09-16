"""Project External Agent CLI events onto the public Workflow stream.

The Command example forwards every normalized CLI event through
``get_stream_writer()``. Text deltas are concatenated as assistant text;
lifecycle and failure events are rendered as short diagnostic lines.
"""


def _text(value):
    return value if isinstance(value, str) else ""


def output(event, origin):
    if event.get("method") != "custom":
        return ""
    params = event.get("params")
    data = params.get("data") if isinstance(params, dict) else None
    if not isinstance(data, dict):
        return ""

    kind = data.get("kind")
    payload = data.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if kind == "text_delta":
        return _text(payload.get("text"))
    if kind == "run_started":
        return f"[external agent started] {_text(payload.get('session_id'))}\n"
    if kind == "session_resolved":
        return (
            "[external agent session] "
            f"{_text(payload.get('conversation_id'))}\n"
        )
    if kind == "run_failed":
        return (
            "[external agent failed] "
            f"{_text(payload.get('code'))}: {_text(payload.get('message'))}\n"
        )
    if kind == "run_finished":
        return f"[external agent {_text(payload.get('status'))}]\n"
    if kind == "denied_actions":
        return f"[external agent denied] {payload.get('actions', [])}\n"
    return ""


def run_output(event, origin):
    if event.get("type") == "agent_shell.workflow_run":
        return f'Workflow {event.get("status", "")}\n'
    return ""
