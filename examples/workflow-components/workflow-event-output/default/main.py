"""Render Workflow-owned raw v3 events.

Read ``event["method"]`` before interpreting ``event["params"]["data"]``;
each LangGraph channel has its own payload shape. ``origin`` contains only
Agent Shell product identity. Returning an empty string filters an event; the
complete contract is documented in
``docs/wizard-pages/workflow-event-output-config.md``.
"""

def _details(summary, message):
    return f'<details type="workflow"><summary>*{summary}*</summary>{message}</details>\n'

def output(event, origin):
    method = str(event.get("method", ""))
    params = event.get("params")
    data = params.get("data") if isinstance(params, dict) else None
    if method == "custom":
        return _details("Workflow Custom", str(data))
    if method in {"values", "updates", "tasks", "checkpoints", "input", "input.requested", "debug"}:
        return _details(f"Workflow {method}", str(data))
    return ""


def run_output(event, origin):
    if event.get("type") == "agent_shell.workflow_run":
        return f'Workflow {event.get("status", "")}\n'
    return ""
