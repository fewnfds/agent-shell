from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from agent_shell.api.errors import management_error
from agent_shell.http_surface import (
    API_KEY_BEARER_SCHEME,
    http_surface,
    management_api_router,
    openai_compat_api_router,
)
from agent_shell.runtime.agent_runtime import RunExecution
from agent_shell.runtime.detached_tasks import DetachedTaskManager
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.request_snapshot import RequestSnapshotRuntime
from agent_shell.security import ApiKeyPolicyError, validate_api_key_policy
from agent_shell.settings import Settings, bearer_token_is_valid
from agent_shell.storage.api_server import ApiServerStore
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.workflows import WorkflowStore


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
    detached_tasks: DetachedTaskManager,
    on_disconnect: Literal["cancel", "continue"],
    cancel_lifecycle: Callable[[], Awaitable[None]],
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

    run_id = (
        execution.identity.run_id
        if execution.identity is not None
        else "unbound"
    )
    producer = detached_tasks.create(
        consume_execution(),
        name=f"request-workflow:{run_id}",
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
        disconnected = not producer.done()
        if disconnected and on_disconnect == "cancel":
            producer.cancel()
            detached_tasks.create(
                cancel_lifecycle(),
                name=f"cancel-workflow-lifecycle:{execution.identity.lifecycle_id if execution.identity else 'unbound'}",
            )


async def _completion_result(
    execution: RunExecution,
    *,
    detached_tasks: DetachedTaskManager,
    on_disconnect: Literal["cancel", "continue"],
    cancel_lifecycle: Callable[[], Awaitable[None]],
) -> tuple[str, dict[str, int]]:
    queue: asyncio.Queue[tuple[Literal["result", "error"], object]] = asyncio.Queue(
        maxsize=1
    )
    detached = asyncio.Event()

    async def consume_execution() -> None:
        try:
            result = await execution.run()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if not detached.is_set():
                await queue.put(("error", exc))
        else:
            if not detached.is_set():
                await queue.put(("result", result))

    run_id = execution.identity.run_id if execution.identity else "unbound"
    producer = detached_tasks.create(
        consume_execution(),
        name=f"request-workflow:{run_id}",
    )
    try:
        kind, value = await queue.get()
        if kind == "error":
            if isinstance(value, BaseException):
                raise value
            raise RuntimeError("the Workflow execution failed without an exception")
        if not isinstance(value, tuple) or len(value) != 2:
            raise RuntimeError("the Workflow execution returned an invalid result")
        return value
    except asyncio.CancelledError:
        detached.set()
        if on_disconnect == "cancel":
            producer.cancel()
            detached_tasks.create(
                cancel_lifecycle(),
                name=f"cancel-workflow-lifecycle:{execution.identity.lifecycle_id if execution.identity else 'unbound'}",
            )
        raise


def build_api_server_router(
    store: ApiServerStore,
    workflows: WorkflowStore,
    agents: AgentConfigStore,
    runtime: RequestSnapshotRuntime,
    settings: Settings,
    events: ApiServerEventHub,
    message_interception: MessageInterceptionState,
    detached_tasks: DetachedTaskManager,
) -> APIRouter:
    router = APIRouter()
    management_router = management_api_router()
    compat_router = openai_compat_api_router()

    def public_settings(request: Request) -> dict[str, object]:
        current = store.settings()
        return {
            "enabled": current["enabled"],
            "status": "running" if current["enabled"] else "stopped",
            "api_key": {"configured": bool(current["api_key_configured"])},
            "message_interception_enabled": current[
                "message_interception_enabled"
            ],
            **http_surface(request),
            "runtime": "model_streaming",
        }

    @management_router.get("/api-server")
    def get_api_server_settings(request: Request) -> dict[str, object]:
        return public_settings(request)

    @management_router.put("/api-server", response_model=None)
    def update_api_server_settings(
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
        )
        events.publish_nowait({"type": "settings_changed"})
        return public_settings(request)

    @management_router.post("/api-server/start")
    def start_api_server(request: Request) -> dict[str, object]:
        store.set_enabled(True)
        events.publish_nowait({"type": "settings_changed"})
        return public_settings(request)

    def interception_snapshot() -> dict[str, object]:
        return {
            "enabled": bool(store.settings()["message_interception_enabled"]),
            "latest": message_interception.latest(),
        }

    @management_router.get("/message-interception")
    def get_message_interception() -> dict[str, object]:
        return interception_snapshot()

    @management_router.put("/message-interception")
    def update_message_interception(
        payload: MessageInterceptionUpdate,
    ) -> dict[str, object]:
        currently_enabled = bool(
            store.settings()["message_interception_enabled"]
        )
        if payload.enabled and not currently_enabled:
            message_interception.clear()
        store.set_message_interception_enabled(payload.enabled)
        events.publish_nowait({"type": "message_interception_changed"})
        return interception_snapshot()

    @management_router.post("/api-server/stop")
    def stop_api_server(request: Request) -> dict[str, object]:
        store.set_enabled(False)
        events.publish_nowait({"type": "settings_changed"})
        return public_settings(request)

    @management_router.get("/api-server/events")
    def api_server_events() -> StreamingResponse:
        return StreamingResponse(
            events.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @compat_router.get(
        "/models",
        openapi_extra={"security": [{API_KEY_BEARER_SCHEME: []}]},
    )
    def models() -> JSONResponse:
        if not store.is_enabled():
            return _openai_error(503, "api_server_stopped", "The API server is stopped.")
        workflow_models = [
            _model_object(item["name"])
            for item in workflows.list_items(enabled_only=True)
            if item["is_model_entry"]
        ]
        agent_models = [
            _model_object(item["name"])
            for item in agents.list_items("main_agents")
            if item["is_model_entry"]
        ]
        return JSONResponse(
            content={"object": "list", "data": [*workflow_models, *agent_models]}
        )

    @compat_router.post(
        "/chat/completions",
        response_model=None,
        openapi_extra={"security": [{API_KEY_BEARER_SCHEME: []}]},
    )
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        server_settings = await asyncio.to_thread(store.settings)
        if not server_settings["enabled"]:
            return _openai_error(503, "api_server_stopped", "The API server is stopped.")
        body = await request.body()
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
            request_snapshot = await runtime.capture()
        except Exception:
            return _openai_error(
                500,
                "configuration_snapshot_failed",
                "The current Graph configuration could not be captured.",
            )
        workflow = request_snapshot.workflow_by_name(model)
        main_agent = request_snapshot.main_agent_by_name(model)
        workflow_entry = (
            workflow is not None
            and workflow["enabled"]
            and workflow["is_model_entry"]
        )
        agent_entry = (
            main_agent is not None and main_agent["is_model_entry"]
        )
        if not workflow_entry and not agent_entry:
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
            if agent_entry:
                execution = await lifecycle_coordinator.start_agent(
                    main_agent,
                    messages,
                    request_id=getattr(request.state, "request_id", ""),
                    public_model=model,
                )
                entry = main_agent
            else:
                execution = await lifecycle_coordinator.start_workflow(
                    workflow,
                    messages,
                    request_id=getattr(request.state, "request_id", ""),
                    public_model=model,
                )
                entry = workflow
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
                    detached_tasks=detached_tasks,
                    on_disconnect=entry["on_disconnect"],
                    cancel_lifecycle=lifecycle_coordinator.cancel_active_runs,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        try:
            content, _usage = await _completion_result(
                execution,
                detached_tasks=detached_tasks,
                on_disconnect=entry["on_disconnect"],
                cancel_lifecycle=lifecycle_coordinator.cancel_active_runs,
            )
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

    router.include_router(management_router)
    router.include_router(compat_router)
    return router
