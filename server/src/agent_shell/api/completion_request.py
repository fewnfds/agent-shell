from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from fastapi.routing import APIRoute
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_shell.runtime.detached_tasks import DetachedTaskManager


logger = logging.getLogger(__name__)


class CompletionRequest:
    """Own transport termination independently of the request's Run policies."""

    def __init__(self, detached_tasks: DetachedTaskManager) -> None:
        self._tasks = detached_tasks
        self._body_received = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._completed = False
        self._response_started = False
        self._response_sent = False
        self._send_lock = asyncio.Lock()
        self._on_disconnect: Callable[[], Awaitable[None]] | None = None
        self._notified = False

    def bind_disconnect(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._on_disconnect = callback
        self._notify_disconnect()

    def _mark_disconnected(self) -> None:
        if self._completed or self._disconnected.is_set():
            return
        self._disconnected.set()
        self._notify_disconnect()

    def _notify_disconnect(self) -> None:
        if (
            not self._disconnected.is_set()
            or self._on_disconnect is None
            or self._notified
        ):
            return
        self._notified = True
        self._tasks.create(self._notify(), name="completion-disconnect")

    async def _notify(self) -> None:
        assert self._on_disconnect is not None
        try:
            await self._on_disconnect()
        except Exception:
            logger.exception("Could not apply the completion disconnect policy.")

    async def run(
        self, app: ASGIApp, scope: Scope, receive: Receive, send: Send
    ) -> None:
        async def receive_body() -> Message:
            if self._body_received.is_set():
                # This owner now reads the real receive channel. Keep the
                # response draining independently of the HTTP subscription;
                # only the coordinator may cancel a Run.
                await asyncio.Future()
            message = await receive()
            if message["type"] == "http.disconnect":
                self._mark_disconnected()
            elif message["type"] == "http.request" and not message.get(
                "more_body", False
            ):
                self._body_received.set()
            return message

        async def send_response(message: Message) -> None:
            async with self._send_lock:
                if self._disconnected.is_set():
                    return
                try:
                    await send(message)
                except OSError:
                    # ASGI's closed-send error is another notification from
                    # this same transport, not a task-cancellation heuristic.
                    self._mark_disconnected()
                    return
                if message["type"] == "http.response.start":
                    self._response_started = True
                elif message["type"] == "http.response.body" and not message.get(
                    "more_body", False
                ):
                    self._response_sent = self._completed = True

        async def finish_disconnected_response() -> None:
            # Outer HTTP middleware still needs a complete ASGI response even
            # when the transport is gone. Keep this serialized with any send
            # already in progress, and discard the background response later.
            async with self._send_lock:
                try:
                    if not self._response_started:
                        await send(
                            {"type": "http.response.start", "status": 204, "headers": []}
                        )
                        self._response_started = True
                    if not self._response_sent:
                        await send(
                            {"type": "http.response.body", "body": b"", "more_body": False}
                        )
                        self._response_sent = True
                except OSError:
                    pass

        async def respond() -> None:
            try:
                await app(scope, receive_body, send_response)
            except ClientDisconnect:
                if not self._disconnected.is_set():
                    raise
            except Exception:
                if not self._disconnected.is_set():
                    raise
                logger.exception("Completion failed after the client disconnected.")
            finally:
                self._completed = True

        async def listen() -> None:
            # Read the body through Request first; two readers must never
            # compete for either request chunks or the disconnect event.
            await self._body_received.wait()
            while not self._completed:
                message = await receive()
                if message["type"] == "http.disconnect":
                    self._mark_disconnected()
                    return

        response = self._tasks.create(respond(), name="completion-response")
        listener = asyncio.create_task(listen(), name="completion-disconnect-listener")
        disconnected = asyncio.create_task(self._disconnected.wait())
        try:
            await asyncio.wait(
                (response, listener, disconnected),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if listener.done():
                listener.result()
            if not self._disconnected.is_set():
                await response
            elif response.done():
                response.result()
            if self._disconnected.is_set():
                await finish_disconnected_response()
        finally:
            listener.cancel()
            disconnected.cancel()
            if not self._disconnected.is_set() and not response.done():
                response.cancel()
            await asyncio.gather(listener, disconnected, return_exceptions=True)
            if not self._disconnected.is_set():
                await asyncio.gather(response, return_exceptions=True)


class CompletionRoute(APIRoute):
    """Limit request lifecycle handling to the OpenAI completion endpoint."""

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        lifecycle = CompletionRequest(scope["app"].state.detached_tasks)
        scope.setdefault("state", {})["completion_request"] = lifecycle
        await lifecycle.run(super().handle, scope, receive, send)
