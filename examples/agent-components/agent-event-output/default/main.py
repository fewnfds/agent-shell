"""A minimal Agent Event Output implementation.

The extension receives the raw LangGraph v3 envelope. Read ``method`` first,
then inspect the channel-specific object under ``params["data"]``. Product
identity (for example the Agent profile) is supplied separately in ``origin``.
Returning an empty string filters an event; the complete contract is documented
in ``docs/wizard-pages/agent-event-output-config.md``.
"""

# Per-output-package state, keyed by official namespace/model Run/block identity.
# Only lengths are retained; detection and buffering belong to PIIMiddleware.
_emitted = {}


def output(event, origin):
    if event.get("method") != "messages" or not origin.get("agent_profile_id"):
        return ""
    params = event.get("params")
    data = params.get("data") if isinstance(params, dict) else None
    payload = data if isinstance(data, dict) else (
        data[0] if isinstance(data, (list, tuple)) and len(data) == 2 else None
    )
    if not isinstance(payload, dict):
        text = getattr(payload, "text", None)
        return text if isinstance(text, str) else ""
    metadata = data[1] if isinstance(data, (list, tuple)) and len(data) == 2 else payload.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    scope = (tuple(params.get("namespace") or ()), metadata.get("run_id", ""))
    key = (*scope, payload.get("index"))
    event_name = payload.get("event")
    if event_name in {"message-finish", "error"}:
        for active in tuple(_emitted):
            if active[:2] == scope:
                _emitted.pop(active)
        return ""
    if event_name == "content-block-start":
        _emitted[key] = 0
    if event_name == "content-block-delta":
        delta = payload.get("delta")
        if isinstance(delta, dict):
            text = str(delta.get("text") or delta.get("reasoning") or "")
            _emitted[key] = _emitted.get(key, 0) + len(text)
            return text
    if event_name == "content-block-finish":
        content = payload.get("content")
        offset = _emitted.pop(key, 0)
        if isinstance(content, dict):
            return str(content.get("text") or content.get("reasoning") or "")[offset:]
    return ""
