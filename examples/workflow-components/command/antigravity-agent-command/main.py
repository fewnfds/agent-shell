"""Run the External Agent bound to this Command Node.

Input contract::

    shared_vars.external_agent_run = {
        "prompt": "optional prompt override",
        "conversation": "optional conversation ID",
    }

When ``prompt`` is omitted, the Command reads the request messages from the
Lifecycle Store and uses the last ``user`` message. The bound External Agent
preset owns the system prompt; this example does not flatten ``system`` or
``assistant`` history into the CLI prompt.

Output contract::

    shared_vars.external_agent_result = {
        "status": "success | timeout | denied | failed",
        "response": "...",
        "conversation_id": "...",
        "conversation_requested": "...",
        "conversation_reused": true | false | null,
        "denied_actions": [...],
        "error_code": "..." | null,
        "error_message": "..." | null,
        "session_directory": "...",
        "event_log": "...",
        "stderr_log": "...",
        "result_file": "...",
    }

Every CLI event is also forwarded through ``get_stream_writer()`` as a
``{"kind", "payload", "at"}`` payload. Use a Workflow Event Output component to
project those ``custom`` events onto the public stream.
"""

from langgraph.config import get_stream_writer
from langgraph.types import Command

from agent_shell.runtime.lifecycle_store import (
    LIFECYCLE_INPUT_KEY,
    lifecycle_input_namespace,
)


def _required_text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_text(value, path):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string when set")
    return value.strip()


async def _request_prompt(runtime):
    store = getattr(runtime, "store", None)
    context = getattr(runtime, "context", None)
    if store is None or context is None:
        raise RuntimeError("runtime.store and runtime.context are required")
    item = await store.aget(
        lifecycle_input_namespace(context.lifecycle_id),
        LIFECYCLE_INPUT_KEY,
    )
    messages = item.value.get("messages") if item is not None else None
    if not isinstance(messages, list):
        raise RuntimeError("the Lifecycle request messages are unavailable")
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(
                "the last user message must contain non-empty text content"
            )
        return content.strip()
    raise ValueError("the Lifecycle request contains no user message")


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        if not isinstance(shared_vars, dict):
            raise ValueError("state.shared_vars must be an object")
        request = shared_vars.get("external_agent_run", {})
        if not isinstance(request, dict):
            raise ValueError("shared_vars.external_agent_run must be an object")

        prompt = (
            _required_text(
                request.get("prompt"),
                "shared_vars.external_agent_run.prompt",
            )
            if "prompt" in request
            else await _request_prompt(runtime)
        )
        conversation = _optional_text(
            request.get("conversation"),
            "shared_vars.external_agent_run.conversation",
        )

        context = runtime.context
        if context is None:
            raise RuntimeError("runtime.context is unavailable")
        external_agent = getattr(context, "external_agent", None)
        if external_agent is None:
            raise RuntimeError(
                "This Command Node has no bound External Agent preset"
            )

        writer = get_stream_writer()

        def forward_event(event):
            writer(
                {
                    "kind": event.kind,
                    "payload": dict(event.payload),
                    "at": event.at,
                }
            )

        result = await external_agent.run(
            prompt,
            conversation=conversation,
            on_event=forward_event,
        )
        return Command(
            update={
                "shared_vars": {
                    "external_agent_result": {
                        "status": result.status,
                        "response": result.response,
                        "conversation_id": result.conversation_id,
                        "conversation_requested": result.conversation_requested,
                        "conversation_reused": result.conversation_reused,
                        "denied_actions": list(result.denied_actions),
                        "error_code": result.error_code,
                        "error_message": result.error_message,
                        "session_directory": result.session_directory,
                        "event_log": result.event_log,
                        "stderr_log": result.stderr_log,
                        "result_file": result.result_file,
                    }
                }
            }
        )

    return command
