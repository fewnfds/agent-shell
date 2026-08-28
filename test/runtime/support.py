from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent_shell.runtime.agent_builder import _build_chat_model
from agent_shell.runtime.agent_runtime import RunExecution

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.output_projection import EventOutputProjectionStream, OutputProjector
from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_scheduler import LifecycleResponseScheduler
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
)
from agent_shell.runtime.output_stream import (
    ModelCallBoundary,
    OutputEvent,
    V3EventNormalizer,
)


def _render_template(template: str, event: dict[str, object]) -> str:
    return re.sub(
        r"{{\s*([^{}]+?)\s*}}",
        lambda match: str(event.get(match.group(1).strip(), "")),
        template,
    )


def output_renderer(
    templates: dict[str, str] | None = None,
    *,
    enabled: set[str] | None = None,
) -> Callable[[dict[str, object]], str]:
    resolved_templates = templates or {"assistant_text": "{{message}}"}
    resolved_enabled = set(resolved_templates) if enabled is None else enabled

    def output(event: dict[str, object]) -> str:
        event_type = str(event["event_type"])
        if event_type not in resolved_enabled:
            return ""
        if (
            event_type in {"assistant_text", "reasoning"}
            and event["phase"] != "delta"
            and not (
                isinstance(event["data"], dict)
                and event["data"].get("type") in {"image", "audio", "video", "file"}
            )
        ):
            return ""
        return _render_template(
            resolved_templates.get(event_type, "{{message}}"),
            event,
        )

    return output


def response_scheduler(
    projector,
    policy: ResponseStreamPolicy | None = None,
) -> LifecycleResponseScheduler:
    return LifecycleResponseScheduler(
        policy or ResponseStreamPolicy(),
        projection_stream=EventOutputProjectionStream(projector),
        lifecycle_id="",
        origin_run_id="",
        origin_workflow_id="",
    )


@pytest.fixture
def provider_http_clients():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    sync_client = httpx.Client(transport=httpx.MockTransport(handler))
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    clients = SimpleNamespace(
        sync_client=sync_client,
        async_client=async_client,
    )
    try:
        yield clients
    finally:
        sync_client.close()
        asyncio.run(async_client.aclose())


def message_envelope(
    payload: dict,
    *,
    run_id: str = "run-main_agent",
    agent_name: str = "Main Agent",
    namespace: list[str] | None = None,
    timestamp: int = 1,
) -> dict:
    return {
        "method": "messages",
        "params": {
            "namespace": namespace or [],
            "timestamp": timestamp,
            "data": (
                payload,
                {
                    "run_id": run_id,
                    "lc_agent_name": agent_name,
                    "langgraph_node": "model",
                },
            ),
        },
    }


class EventRun:
    def __init__(self, events: list[dict]) -> None:
        self._events = iter(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    def __aiter__(self):
        async def events():
            for event in self._events:
                yield event

        return events()

    async def output(self):
        return None


class EventGraph:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def astream_events(
        self, _input, *, config: dict, version: str, transformers: tuple = ()
    ):
        assert config == {"recursion_limit": 1_000_000}
        assert version == "v3"
        assert transformers
        return EventRun(self._events)


class NoopMiddlewareRuntime:
    async def close(self) -> None:
        pass


def noop_middleware_runtime() -> NoopMiddlewareRuntime:
    return NoopMiddlewareRuntime()


class NoopMediaResponse:
    @staticmethod
    async def project(_event) -> None:
        return None

    @property
    def assets(self) -> list[dict]:
        return []

    @staticmethod
    def structured_blocks(_response) -> list[dict]:
        return []


def noop_media_response() -> NoopMediaResponse:
    return NoopMediaResponse()
