from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from agent_shell.redaction import redact_for_boundary

def _type_name(value: Any) -> str:
    value_type = value if isinstance(value, type) else type(value)
    module = getattr(value_type, "__module__", "")
    name = getattr(value_type, "__qualname__", value_type.__name__)
    return f"{module}.{name}" if module else name


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value, depth=depth + 1)
    if callable(getattr(value, "get_secret_value", None)):
        return "**********"
    if depth >= 12:
        return {"type": _type_name(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_json_safe(item, depth=depth + 1) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_safe(getattr(value, field.name), depth=depth + 1)
            for field in fields(value)
        }
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"), depth=depth + 1)
        except (TypeError, ValueError):
            try:
                return _json_safe(model_dump(), depth=depth + 1)
            except (TypeError, ValueError):
                pass
    return {"type": _type_name(value)}


def _message_role(message: Any) -> str:
    return {
        "human": "user",
        "ai": "assistant",
        "system": "system",
        "tool": "tool",
        "function": "function",
    }.get(str(getattr(message, "type", "")), str(getattr(message, "type", "message")))


def _message_payload(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": _message_role(message),
        "content": _json_safe(getattr(message, "content", "")),
    }
    for field in ("name", "id", "tool_call_id", "status"):
        value = getattr(message, field, None)
        if value is not None and value != "":
            payload[field] = _json_safe(value)
    for field in ("tool_calls", "invalid_tool_calls", "additional_kwargs"):
        value = getattr(message, field, None)
        if value:
            payload[field] = _json_safe(value)
    return payload


def _model_payload(model: Any) -> dict[str, Any]:
    name = (
        getattr(model, "model_name", None)
        or getattr(model, "model", None)
        or getattr(model, "model_id", None)
    )
    payload: dict[str, Any] = {"type": _type_name(model)}
    if isinstance(name, str) and name:
        payload["name"] = name
    configuration: dict[str, Any] = {}
    safe_fields = (
        "base_url",
        "openai_api_base",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "max_tokens_to_sample",
        "top_p",
        "top_k",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "stop_sequences",
        "timeout",
        "request_timeout",
        "max_retries",
        "retries",
        "streaming",
        "stream_usage",
        "reasoning_effort",
        "effort",
        "service_tier",
        "logprobs",
        "top_logprobs",
        "thinking_level",
        "thinking_budget",
        "include_thoughts",
    )
    for field in safe_fields:
        value = getattr(model, field, None)
        if value is not None:
            configuration[field] = _json_safe(value)
    model_kwargs = getattr(model, "model_kwargs", None)
    if isinstance(model_kwargs, Mapping):
        for field in safe_fields:
            if field not in configuration and field in model_kwargs:
                configuration[field] = _json_safe(model_kwargs[field])
    if configuration:
        payload["configuration"] = configuration
    return payload


def _tool_payload(tool: Any) -> Any:
    from langchain_core.utils.function_calling import convert_to_openai_tool

    return _json_safe(convert_to_openai_tool(tool))


def serialize_model_request(request: Any) -> dict[str, Any]:
    """Return the safe, model-visible surface of a final LangChain ModelRequest."""

    messages = list(request.messages)
    if request.system_message is not None:
        messages = [request.system_message, *messages]
    response_format = request.response_format
    response_payload = None
    if response_format is not None:
        schema = getattr(response_format, "schema", None)
        response_value = (
            {"schema": _json_safe(schema)}
            if schema is not None
            else _json_safe(response_format)
        )
        response_payload = {
            "type": _type_name(response_format),
            "value": response_value,
        }
    return {
        "model": _model_payload(request.model),
        "messages": [_message_payload(message) for message in messages],
        "tools": [_tool_payload(tool) for tool in request.tools],
        "tool_choice": _json_safe(request.tool_choice),
        "response_format": response_payload,
        "model_settings": redact_for_boundary(
            "request-trace", _json_safe(request.model_settings)
        ),
    }


CaptureCallback = Callable[[dict[str, Any]], None | Awaitable[None]]


def make_model_request_observer_middleware(
    capture: CaptureCallback,
    *,
    context: Mapping[str, object] | Callable[[], Mapping[str, object]] | None = None,
) -> Any:
    """Observe the final ModelRequest and continue to the next handler unchanged."""

    from langchain.agents.middleware import AgentMiddleware

    def observed_payload(request: Any) -> dict[str, Any]:
        payload = serialize_model_request(request)
        if context is not None:
            metadata = context() if callable(context) else context
            payload.update(metadata)
        return payload

    class ModelRequestObserverMiddleware(AgentMiddleware):
        def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
            result = capture(observed_payload(request))
            if inspect.isawaitable(result):
                raise RuntimeError("async observer callback used in sync model call")
            return handler(request)

        async def awrap_model_call(
            self, request: Any, handler: Callable[[Any], Awaitable[Any]]
        ) -> Any:
            result = capture(observed_payload(request))
            if inspect.isawaitable(result):
                await result
            return await handler(request)

    return ModelRequestObserverMiddleware()
