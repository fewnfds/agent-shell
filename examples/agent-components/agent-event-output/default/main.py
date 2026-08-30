"""A minimal Agent Event Output implementation.

The extension receives the raw LangGraph v3 envelope. Read ``method`` first,
then inspect the channel-specific object under ``params["data"]``. Product
identity (for example the Agent profile) is supplied separately in ``origin``.
Returning an empty string filters an event; the complete contract is documented
in ``docs/wizard-pages/agent-event-output-config.md``.
"""

def output(event, origin):
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
    return str(delta.get("text") or delta.get("reasoning") or "")


def run_output(event, origin):
    return ""
