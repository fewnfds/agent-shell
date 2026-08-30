from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import pytest

from agent_shell.runtime.agent_builder import _build_chat_model
from agent_shell.runtime.agent_runtime import RunExecution

from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.runtime.event_origin import RunEventOriginResolver
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.response_stream_policy import ResponseStreamPolicy
from agent_shell.runtime.response_scheduler import LifecycleResponseScheduler
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
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
) -> Callable[[dict[str, object], dict[str, object]], str]:
    resolved_templates = templates or {"assistant_text": "{{message}}"}
    resolved_enabled = set(resolved_templates) if enabled is None else enabled
    streamed_blocks: set[tuple[str, int]] = set()

    def output(event: dict[str, object], origin: dict[str, object]) -> str:
        method = str(event.get("method") or "")
        params = event.get("params")
        data = params.get("data") if isinstance(params, dict) else None
        phase = "delta"
        message = ""
        event_type = method
        if method == "messages" and isinstance(data, (list, tuple)) and len(data) == 2:
            payload = data[0]
            if isinstance(payload, dict):
                raw_event = str(payload.get("event") or "")
                if raw_event in {"content-block-delta", "content-block-start", "content-block-finish"}:
                    block = payload.get("delta") or payload.get("content")
                    if isinstance(block, dict):
                        block_type = str(block.get("type") or "")
                        event_type = "reasoning" if "reasoning" in block_type else "assistant_text"
                        metadata = data[1] if isinstance(data[1], dict) else {}
                        run_id = str(metadata.get("run_id") or "")
                        index = payload.get("index")
                        block_key = (run_id, index) if isinstance(index, int) else None
                        if raw_event == "content-block-start" and block_key is not None:
                            streamed_blocks.add(block_key)
                        elif raw_event == "content-block-delta" and block_key is not None:
                            streamed_blocks.add(block_key)
                        # A streamed finish payload is a snapshot. Suppress it
                        # after real deltas; a finish without a prior block is
                        # the whole-message form and remains visible.
                        if raw_event != "content-block-finish" or block_key not in streamed_blocks:
                            message = str(block.get("text") or block.get("reasoning") or "")
                        elif block_type in {"text", "reasoning"}:
                            return ""
                phase = "delta" if raw_event in {"content-block-delta", "content-block-finish"} else "start"
            else:
                message = str(getattr(payload, "text", "") or "")
                event_type = "assistant_text"
                phase = "delta"
        elif method == "custom":
            message = str(data)
        event = {
            "event_type": event_type,
            "phase": phase,
            "message": message,
            "data": data,
            "source_type": "agent" if origin.get("agent_profile_id") else "non_agent",
            "tool_name": "",
            "tool_call_id": "",
        }
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


def run_output_renderer(
    template: str = "{{status}}",
) -> Callable[[dict[str, object], dict[str, object]], str]:
    """Render Shell's synthetic Run status hook for runtime tests."""

    def run_output(event: dict[str, object], origin: dict[str, object]) -> str:
        if event.get("type") != "agent_shell.workflow_run":
            return ""
        return _render_template(template, event)

    return run_output


def response_scheduler(
    projector,
    policy: ResponseStreamPolicy | None = None,
    *,
    run_output=None,
) -> LifecycleResponseScheduler:
    if run_output is not None:
        from agent_shell.runtime.output_projection import OutputProjector

        projector = OutputProjector(None, run_output=run_output)
    scheduler = LifecycleResponseScheduler(
        policy or ResponseStreamPolicy(),
        lifecycle_id="",
        origin_run_id="",
        origin_workflow_id="",
    )
    return scheduler


def event_origin_resolver(
    main_agent_name: str = "Main Agent",
) -> RunEventOriginResolver:
    return RunEventOriginResolver(
        None,
        main_agent_names=(main_agent_name,),
        default_agent_profile_id="test-agent-profile",
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
        self,
        _input,
        *,
        config: dict,
        version: str,
        transformers: tuple = (),
        **_kwargs,
    ):
        assert config["recursion_limit"] == 1_000_000
        assert set(config) <= {"recursion_limit", "callbacks"}
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

def noop_media_response() -> NoopMediaResponse:
    return NoopMediaResponse()
