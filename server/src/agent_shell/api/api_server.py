from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from agent_shell.api.errors import management_error
from agent_shell.runtime.agent_runtime import RunExecution
from agent_shell.runtime.background_tasks import BackgroundTaskManager
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.request_snapshot import RequestSnapshotRuntime
from agent_shell.security import ApiKeyPolicyError, validate_api_key_policy
from agent_shell.settings import Settings, bearer_token_is_valid
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.runtime_policy import RuntimePolicyStore
from agent_shell.storage.workflows import WorkflowStore


class _BodyTooLarge(RuntimeError):
    pass


async def _read_bounded_body(request: Request, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            pass
        else:
            if declared_length > limit:
                raise _BodyTooLarge

    body = bytearray()
    async for chunk in request.stream():
        if len(chunk) > limit - len(body):
            raise _BodyTooLarge
        body.extend(chunk)
    return bytes(body)


class ApiKeyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["keep", "replace", "clear"] = "keep"
    value: SecretStr | None = None

    @model_validator(mode="after")
    def validate_command(self) -> "ApiKeyCommand":
        if self.operation == "replace":
            if self.value is None:
                raise ValueError("replace requires an API Key")
            secret = self.value.get_secret_value()
            if not bearer_token_is_valid(secret):
                raise ValueError(
                    "API Key must be a non-empty printable ASCII value without spaces"
                )
        elif self.value is not None:
            raise ValueError("keep and clear do not accept an API Key value")
        return self


class ApiServerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: ApiKeyCommand = Field(default_factory=ApiKeyCommand)
    max_initial_messages: int | None = Field(default=None, ge=1)


class MessageInterceptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class MessageInterceptionState:
    """Keep the latest intercepted OpenAI request in process memory."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._sequence = 0
        self._latest: dict[str, object] | None = None

    def capture(self, *, request_id: str, request_raw_json: str) -> dict[str, object]:
        with self._lock:
            self._sequence += 1
            self._latest = {
                "sequence": self._sequence,
                "intercepted_at": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                "request_id": request_id,
                "request_raw_json": request_raw_json,
            }
            return dict(self._latest)

    def latest(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._latest) if self._latest is not None else None

    def clear(self) -> None:
        with self._lock:
            self._latest = None


class ApiServerEventHub:
    def __init__(self) -> None:
        self._subscribers: set[
            tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, object]]]
        ] = set()
        self._subscribers_lock = Lock()

    async def publish(self, event: dict[str, object]) -> None:
        self.publish_nowait(event)

    def publish_nowait(self, event: dict[str, object]) -> None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        with self._subscribers_lock:
            subscribers = tuple(self._subscribers)
        for owner_loop, queue in subscribers:
            if owner_loop is current_loop:
                self._deliver_nowait(queue, event)
            elif not owner_loop.is_closed():
                owner_loop.call_soon_threadsafe(self._deliver_nowait, queue, event)

    @staticmethod
    def _deliver_nowait(
        queue: asyncio.Queue[dict[str, object]],
        event: dict[str, object],
    ) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=50)
        subscription = (asyncio.get_running_loop(), queue)
        with self._subscribers_lock:
            self._subscribers.add(subscription)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield "data: " + json.dumps(
                    event, ensure_ascii=False, separators=(",", ":")
                ) + "\n\n"
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(subscription)


def _openai_error(
    status_code: int,
    code: str,
    message: str,
    *,
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_openai_error_payload(code, message, status_code=status_code, param=param),
    )


def _openai_error_payload(
    code: str,
    message: str,
    *,
    status_code: int,
    param: str | None = None,
) -> dict[str, object]:
    return {
        "error": {
            "message": message,
            "type": "invalid_request_error" if status_code < 500 else "server_error",
            "param": param,
            "code": code,
        }
    }


def _model_object(model_id: str) -> dict[str, object]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "agent-shell",
    }


def _usage_payload(usage: dict[str, int]) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
    reasoning_tokens = usage.get("reasoning_tokens")
    if reasoning_tokens is not None:
        payload["completion_tokens_details"] = {
            "reasoning_tokens": reasoning_tokens,
        }
    return payload


def _completion_payload(
    *,
    model: str,
    content: str,
    execution: RunExecution,
) -> dict[str, object]:
    return {
        "id": f"chatcmpl_{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": execution.finish_reason,
            }
        ],
        "usage": _usage_payload(execution.usage),
    }


def _intercepted_completion_payload(*, model: str) -> dict[str, object]:
    return {
        "id": f"chatcmpl_{uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "消息已拦截"},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage_payload({}),
    }


async def _intercepted_completion_stream(model: str) -> AsyncIterator[str]:
    completion_id = f"chatcmpl_{uuid4().hex}"
    created = int(time.time())

    def encode(payload: dict[str, object]) -> str:
        return "data: " + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n\n"

    for delta, finish_reason, usage in (
        ({"role": "assistant"}, None, None),
        ({"content": "消息已拦截"}, None, None),
        ({}, "stop", _usage_payload({})),
    ):
        payload: dict[str, object] = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }
        if usage is not None:
            payload["usage"] = usage
        yield encode(payload)
    yield "data: [DONE]\n\n"


async def _completion_stream(
    execution: RunExecution,
    model: str,
    *,
    background_tasks: BackgroundTaskManager,
    cancel_on_disconnect: bool,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl_{uuid4().hex}"
    created = int(time.time())

    def encode(payload: dict[str, object]) -> str:
        return "data: " + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n\n"

    queue: asyncio.Queue[tuple[Literal["text", "error", "done"], object]] = (
        asyncio.Queue(maxsize=1)
    )
    detached = asyncio.Event()

    async def deliver(
        kind: Literal["text", "error", "done"],
        value: object,
    ) -> None:
        if not detached.is_set():
            await queue.put((kind, value))

    async def consume_execution() -> None:
        cancelled = False
        try:
            async for text in execution.stream_text():
                if text:
                    await deliver("text", text)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:
            await deliver("error", exc)
        finally:
            if not cancelled:
                await deliver("done", None)

    workflow_run_id = (
        execution.identity.workflow_run_id
        if execution.identity is not None
        else "unbound"
    )
    producer = background_tasks.create_detached_task(
        consume_execution(),
        name=f"request-workflow:{workflow_run_id}",
    )
    try:
        yield encode(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
        )
        while True:
            kind, value = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                if isinstance(value, BaseException):
                    raise value
                raise RuntimeError("the Workflow execution failed without an exception")
            yield encode(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": str(value)},
                            "finish_reason": None,
                        }
                    ],
                }
            )
    except AgentRuntimeError as exc:
        yield encode(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "error"}
                ],
                "error": _openai_error_payload(
                    exc.code,
                    exc.safe_message,
                    status_code=exc.status_code,
                )["error"],
            }
        )
        yield "data: [DONE]\n\n"
        return
    except Exception:
        yield encode(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": "error"}
                ],
                "error": _openai_error_payload(
                    "internal_error",
                    "An internal operation failed.",
                    status_code=500,
                )["error"],
            }
        )
        yield "data: [DONE]\n\n"
        return
    else:
        yield encode(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": execution.finish_reason,
                    }
                ],
                "usage": _usage_payload(execution.usage),
            }
        )
        yield "data: [DONE]\n\n"
    finally:
        detached.set()
        try:
            while True:
                queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        if cancel_on_disconnect and not producer.done():
            if producer.cancel():
                background_tasks.create_detached_task(
                    execution.cancel(),
                        name=f"cancel-request-workflow:{workflow_run_id}",
                )


def build_api_server_router(
    store: ApiServerStore,
    workflows: WorkflowStore,
    runtime: RequestSnapshotRuntime,
    settings: Settings,
    events: ApiServerEventHub,
    message_interception: MessageInterceptionState,
    runtime_policy: RuntimePolicyStore,
    background_tasks: BackgroundTaskManager,
) -> APIRouter:
    router = APIRouter()

    def public_settings(request: Request) -> dict[str, object]:
        current = store.settings()
        base = str(request.base_url).rstrip("/")
        return {
            "enabled": current["enabled"],
            "status": "running" if current["enabled"] else "stopped",
            "api_key": {"configured": bool(current["api_key_configured"])},
            "max_initial_messages": current["max_initial_messages"],
            "message_interception_enabled": current[
                "message_interception_enabled"
            ],
            "api_base_url": f"{base}/v1",
            "models_endpoint": f"{base}/v1/models",
            "chat_completions_endpoint": f"{base}/v1/chat/completions",
            "runtime": "model_streaming",
        }

    @router.get("/api/api-server")
    async def get_api_server_settings(request: Request) -> dict[str, object]:
        return public_settings(request)

    @router.put("/api/api-server", response_model=None)
    async def update_api_server_settings(
        payload: ApiServerSettingsUpdate, request: Request
    ) -> dict[str, object] | JSONResponse:
        secret = (
            payload.api_key.value.get_secret_value()
            if payload.api_key.value is not None
            else None
        )
        current_key = store.api_key()
        candidate_key = {
            "keep": current_key,
            "replace": secret,
            "clear": None,
        }[payload.api_key.operation]
        try:
            validate_api_key_policy(settings, candidate_key)
        except ApiKeyPolicyError as exc:
            raise management_error(
                422,
                code=exc.code,
                message_key=exc.message_key,
                message=exc.safe_message,
            )
        store.update_settings(
            api_key_operation=payload.api_key.operation,
            api_key=secret,
            max_initial_messages=payload.max_initial_messages,
        )
        await events.publish({"type": "settings_changed"})
        return public_settings(request)

    @router.post("/api/api-server/start")
    async def start_api_server(request: Request) -> dict[str, object]:
        store.set_enabled(True)
        await events.publish({"type": "settings_changed"})
        return public_settings(request)

    def interception_snapshot() -> dict[str, object]:
        return {
            "enabled": bool(store.settings()["message_interception_enabled"]),
            "latest": message_interception.latest(),
        }

    @router.get("/api/message-interception")
    async def get_message_interception() -> dict[str, object]:
        return interception_snapshot()

    @router.put("/api/message-interception")
    async def update_message_interception(
        payload: MessageInterceptionUpdate,
    ) -> dict[str, object]:
        currently_enabled = bool(
            store.settings()["message_interception_enabled"]
        )
        if payload.enabled and not currently_enabled:
            message_interception.clear()
        store.set_message_interception_enabled(payload.enabled)
        await events.publish({"type": "message_interception_changed"})
        return interception_snapshot()

    @router.post("/api/api-server/stop")
    async def stop_api_server(request: Request) -> dict[str, object]:
        store.set_enabled(False)
        await events.publish({"type": "settings_changed"})
        return public_settings(request)

    @router.get("/api/api-server/events")
    async def api_server_events() -> StreamingResponse:
        return StreamingResponse(
            events.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/v1/models")
    async def models() -> JSONResponse:
        if not store.is_enabled():
            return _openai_error(503, "api_server_stopped", "The API server is stopped.")
        workflow_models = [
            _model_object(item["name"])
            for item in workflows.list_items(
                enabled_only=True,
                workflow_role="parent",
            )
        ]
        return JSONResponse(content={"object": "list", "data": workflow_models})

    @router.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        server_settings = store.settings()
        if not server_settings["enabled"]:
            return _openai_error(503, "api_server_stopped", "The API server is stopped.")
        try:
            body_limit = runtime_policy.snapshot().chat_completion_body_bytes
            body = await _read_bounded_body(request, body_limit)
        except _BodyTooLarge:
            return _openai_error(
                413,
                "input_body_too_large",
                f"The request body may not exceed {body_limit} bytes.",
            )
        try:
            raw_json = body.decode("utf-8")
            payload = json.loads(raw_json)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _openai_error(400, "invalid_json", "The request body must be valid UTF-8 JSON.")
        if not isinstance(payload, dict):
            return _openai_error(422, "invalid_request", "The request body must be a JSON object.")
        model = payload.get("model")
        if not isinstance(model, str) or not model:
            return _openai_error(422, "model_required", "A model is required.", param="model")
        stream = payload.get("stream", False)
        if not isinstance(stream, bool):
            return _openai_error(
                422,
                "invalid_stream",
                "stream must be a boolean.",
                param="stream",
            )
        messages = payload.get("messages")
        max_initial_messages = int(server_settings["max_initial_messages"])
        if isinstance(messages, list) and len(messages) > max_initial_messages:
            return _openai_error(
                422,
                "input_messages_too_many",
                f"messages cannot contain more than {max_initial_messages} items.",
                param="messages",
            )
        if server_settings["message_interception_enabled"]:
            intercepted = message_interception.capture(
                request_id=getattr(request.state, "request_id", ""),
                request_raw_json=raw_json,
            )
            await events.publish(
                {
                    "type": "message_intercepted",
                    "sequence": intercepted["sequence"],
                }
            )
            if stream:
                return StreamingResponse(
                    _intercepted_completion_stream(model),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                    },
                )
            return JSONResponse(
                content=_intercepted_completion_payload(model=model)
            )
        try:
            request_snapshot = runtime.capture()
        except Exception:
            return _openai_error(
                500,
                "configuration_snapshot_failed",
                "The current Workflow configuration could not be captured.",
            )
        workflow = request_snapshot.workflow_by_name(model)
        if (
            workflow is None
            or not workflow["enabled"]
            or workflow["workflow_role"] != "parent"
        ):
            return _openai_error(
                404,
                "model_not_found",
                "The requested model does not exist.",
                param="model",
            )
        try:
            lifecycle_coordinator = runtime.create_lifecycle_coordinator(
                request_snapshot
            )
            execution = await lifecycle_coordinator.start_parent_workflow(
                workflow,
                messages,
                request_id=getattr(request.state, "request_id", ""),
                public_model=model,
            )
        except AgentRuntimeError as exc:
            issue = (
                exc.validation_report.issues[0]
                if exc.validation_report is not None
                and exc.validation_report.issues
                else None
            )
            return _openai_error(
                exc.status_code,
                issue.code if issue is not None else exc.code,
                issue.message if issue is not None else exc.safe_message,
            )
        except Exception:
            return _openai_error(
                500,
                "internal_error",
                "An internal operation failed.",
        )
        if stream:
            return StreamingResponse(
                _completion_stream(
                    execution,
                    model,
                    background_tasks=background_tasks,
                    cancel_on_disconnect=bool(
                        workflow["cancel_on_upstream_termination"]
                    ),
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        try:
            content, _usage = await execution.run()
        except AgentRuntimeError as exc:
            return _openai_error(
                exc.status_code,
                exc.code,
                exc.safe_message,
            )
        except Exception:
            return _openai_error(
                500,
                "internal_error",
                "An internal operation failed.",
            )
        return JSONResponse(
            content=_completion_payload(
                model=model,
                content=content,
                execution=execution,
            )
        )

    return router
