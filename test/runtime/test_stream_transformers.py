from __future__ import annotations

import asyncio
import json
import warnings
from typing_extensions import TypedDict

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_shell.runtime.agent_runtime import RunExecution
from agent_shell.runtime.output_projection import OutputProjector, WorkflowOutputProjector
from agent_shell.runtime.stream_transformers import RawCustomEventTransformer
from .support import (
    noop_media_response,
    noop_middleware_runtime,
    EventGraph,
    event_origin_resolver,
    message_envelope,
    output_renderer,
    response_scheduler,
)


class _State(TypedDict, total=False):
    value: str


def test_raw_custom_transformer_requests_custom_mode_without_root_child_duplicates() -> None:
    def root_node(state: _State) -> dict[str, str]:
        get_stream_writer()({"source": "root"})
        return {"value": "root"}

    def child_node(state: _State) -> dict[str, str]:
        get_stream_writer()({"source": "child"})
        return {"value": "child"}

    child_builder = StateGraph(_State)
    child_builder.add_node("child_node", child_node)
    child_builder.add_edge(START, "child_node")
    child_builder.add_edge("child_node", END)
    child = child_builder.compile(name="child_graph")

    builder = StateGraph(_State)
    builder.add_node("root_node", root_node)
    builder.add_node("child", child)
    builder.add_edge(START, "root_node")
    builder.add_edge("root_node", "child")
    builder.add_edge("child", END)
    graph = builder.compile()

    async def collect() -> list[tuple[list[str], dict[str, str]]]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stream = await graph.astream_events(
                {},
                version="v3",
                transformers=(RawCustomEventTransformer,),
            )
        events: list[tuple[list[str], dict[str, str]]] = []
        async with stream:
            async for event in stream:
                if event.get("method") == "custom":
                    events.append((
                        list(event["params"]["namespace"]),
                        dict(event["params"]["data"]),
                    ))
        return events

    events = asyncio.run(collect())
    assert [data for _namespace, data in events] == [
        {"source": "root"},
        {"source": "child"},
    ]
    assert events[0][0] == []
    # The child event is visible in the single root raw iterator under its
    # namespace. Its child mux transformer must not re-emit it.
    assert len(events[1][0]) == 1
    assert events[1][0][0].startswith("child:")


def test_agent_execution_projects_real_stream_writer_custom_event() -> None:
    def emit_progress(state: _State) -> dict[str, str]:
        writer = get_stream_writer()
        writer("progress ready")
        writer({"kind": "progress", "progress": "ready"})
        return {"value": "done"}

    builder = StateGraph(_State)
    builder.add_node("emit_progress", emit_progress)
    builder.add_edge(START, "emit_progress")
    builder.add_edge("emit_progress", END)
    graph = builder.compile()

    def workflow_output(event: dict[str, object], origin: dict[str, object]) -> str:
        if event.get("method") != "custom":
            return ""
        params = event.get("params")
        data = params.get("data") if isinstance(params, dict) else None
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return str(data or "")

    projector = WorkflowOutputProjector(
        {},
        workflow_output=workflow_output,
    )
    execution = RunExecution(
        graph=graph,
        input_state={},
        response_scheduler=response_scheduler(projector),
        event_output_projector=projector,
        origin_resolver=event_origin_resolver(),
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    async def collect() -> list[str]:
        return [part async for part in execution.stream_text()]

    assert asyncio.run(collect()) == [
        "progress ready",
        '{"kind":"progress","progress":"ready"}',
    ]
    assert execution.final_state == {"value": "done"}


def test_agent_execution_projects_real_tool_result() -> None:
    @tool
    def inspect_value(value: str) -> str:
        """Return a visible inspection result."""

        return f"inspected:{value}"

    async def call_tool(state: _State, config) -> dict[str, str]:
        result = await inspect_value.ainvoke({"value": "ready"}, config=config)
        return {"value": result}

    builder = StateGraph(_State)
    builder.add_node("call_tool", call_tool)
    builder.add_edge(START, "call_tool")
    builder.add_edge("call_tool", END)
    graph = builder.compile()

    tool_names: dict[str, str] = {}

    def output(event: dict[str, object], origin: dict[str, object]) -> str:
        if event.get("method") != "tools":
            return ""
        params = event.get("params")
        data = params.get("data") if isinstance(params, dict) else None
        if not isinstance(data, dict):
            return ""
        event_name = data.get("event")
        tool_call_id = str(data.get("tool_call_id") or "")
        if event_name == "tool-started":
            tool_names[tool_call_id] = str(data.get("tool_name") or "")
            return ""
        if event_name != "tool-finished":
            return ""
        return (
            f"tool={tool_names.get(tool_call_id, '')} "
            f"output={data.get('output', '')}"
        )

    projector = OutputProjector(output)
    execution = RunExecution(
        graph=graph,
        input_state={},
        response_scheduler=response_scheduler(projector),
        event_output_projector=projector,
        origin_resolver=event_origin_resolver(),
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    async def collect() -> list[str]:
        return [part async for part in execution.stream_text()]

    assert asyncio.run(collect()) == ["tool=inspect_value output=inspected:ready"]
    assert execution.final_state == {"value": "inspected:ready"}


def test_agent_execution_preserves_raw_finish_projection_as_segment_end() -> None:
    def output(event: dict[str, object], origin: dict[str, object]) -> str:
        if event.get("method") != "messages":
            return ""
        params = event.get("params")
        data = params.get("data") if isinstance(params, dict) else None
        if not isinstance(data, (list, tuple)) or len(data) != 2:
            return ""
        payload = data[0]
        if not isinstance(payload, dict):
            return ""
        event_name = payload.get("event")
        if event_name == "content-block-start":
            return "<answer>"
        if event_name == "content-block-delta":
            delta = payload.get("delta")
            return str(delta.get("text", "")) if isinstance(delta, dict) else ""
        if event_name == "content-block-finish":
            return "</answer>"
        return ""

    events = [
        message_envelope(
            {"event": "message-start", "role": "ai", "id": "message-1"}
        ),
        message_envelope(
            {
                "event": "content-block-start",
                "index": 0,
                "content": {"type": "text", "text": ""},
            }
        ),
        message_envelope(
            {
                "event": "content-block-delta",
                "index": 0,
                "delta": {"type": "text-delta", "text": "ready"},
            }
        ),
        message_envelope(
            {
                "event": "content-block-finish",
                "index": 0,
                "content": {"type": "text", "text": "ready"},
            }
        ),
        message_envelope({"event": "message-finish", "usage": {}}),
    ]
    projector = OutputProjector(output)
    execution = RunExecution(
        graph=EventGraph(events),
        input_state={},
        response_scheduler=response_scheduler(projector),
        event_output_projector=projector,
        origin_resolver=event_origin_resolver(),
        middleware_runtime=noop_middleware_runtime(),
        media_response=noop_media_response(),
    )

    async def collect() -> list[str]:
        return [part async for part in execution.stream_text()]

    assert "".join(asyncio.run(collect())) == "<answer>ready</answer>"
