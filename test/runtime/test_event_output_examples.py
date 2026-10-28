from __future__ import annotations

from html import escape
from pathlib import Path
import runpy


def test_all_events_examples_render_streamed_and_atomic_event_families() -> None:
    source_root = Path(__file__).resolve().parents[2] / "examples"
    common_origin = {
        "lifecycle_id": "lifecycle-1",
        "run_id": "workflow-run-1",
        "thread_id": "thread-1",
        "assistant_id": "assistant-1",
        "workflow_node_id": "agent-node",
        "node_invocation_id": "invoke-1",
    }
    main_agent_name = 'Writer <& "[root]">'
    workflow_name = 'Review <& "[flow]">'
    agent_origin = {
        **common_origin,
        "graph_kind": "agent",
        "workflow_id": "",
        "workflow_name": "",
        "main_agent_id": "agent-1",
        "main_agent_name": main_agent_name,
        "agent_profile_id": "agent-1",
        "subagent_profile_id": "",
        "subagent_name": "",
    }
    workflow_origin = {
        **common_origin,
        "graph_kind": "workflow",
        "workflow_id": "workflow-1",
        "workflow_name": workflow_name,
        "main_agent_id": "",
        "main_agent_name": "",
        "agent_profile_id": "",
        "subagent_profile_id": "",
        "subagent_name": "",
    }

    def envelope(method: str, data: object, *, seq: int = 1) -> dict[str, object]:
        return {
            "method": method,
            "seq": seq,
            "params": {
                "namespace": ["agent-node:invoke-1"],
                "timestamp": 123,
                "data": data,
            },
        }

    def message(payload: dict[str, object], *, seq: int = 1) -> dict[str, object]:
        return envelope(
            "messages",
            [payload, {"run_id": "model-run-1", "langgraph_node": "model"}],
            seq=seq,
        )

    def assert_atomic(value: str, identity_prefix: str, scope: str) -> None:
        assert value.startswith("<details open>")
        assert value.endswith("</details>\n")
        assert f"<summary>{identity_prefix}" in value
        assert f"<summary>{scope} · " not in value
        assert "run_id=workflow-run-1" in value

    def assert_stream_end(value: str) -> None:
        assert value.startswith("</div>\n")
        assert value.endswith("</details>\n")
        assert "run_id=workflow-run-1" in value

    for relative_path, origin, scope, name in (
        (
            Path("agent-components/agent-event-output/all-events/main.py"),
            agent_origin,
            "Agent",
            main_agent_name,
        ),
        (
            Path("workflow-components/workflow-event-output/all-events/main.py"),
            workflow_origin,
            "Workflow",
            workflow_name,
        ),
    ):
        namespace = runpy.run_path(str(source_root / relative_path))
        output = namespace["output"]
        segment_end = namespace["segment_end"]
        identity_prefix = escape(f"{scope} [{name}] · ")

        assert_atomic(
            output(message({"event": "message-start", "id": "msg-1"}), origin),
            identity_prefix,
            scope,
        )

        text_start = message({
            "event": "content-block-start",
            "index": 0,
            "content": {"type": "text", "text": ""},
        })
        text_open = output(text_start, origin)
        assert text_open.startswith("<details open>")
        assert f"<summary>{identity_prefix}Assistant text</summary>" in text_open
        assert not text_open.endswith("</details>\n")
        assert_stream_end(segment_end(text_start, origin))
        text_delta = message({
            "event": "content-block-delta",
            "index": 0,
            "delta": {"type": "text-delta", "text": "<answer>"},
        })
        assert output(text_delta, origin) == "&lt;answer&gt;"
        assert_stream_end(output(message({
            "event": "content-block-finish",
            "index": 0,
            "content": {"type": "text", "text": "<answer>"},
        }), origin))

        reasoning_start = message({
            "event": "content-block-start",
            "index": 1,
            "content": {"type": "reasoning", "reasoning": ""},
        })
        reasoning_open = output(reasoning_start, origin)
        assert reasoning_open.startswith("<details open>")
        assert f"<summary>{identity_prefix}Reasoning</summary>" in reasoning_open
        assert_stream_end(segment_end(reasoning_start, origin))
        assert output(message({
            "event": "content-block-delta",
            "index": 1,
            "delta": {"type": "reasoning-delta", "reasoning": "think"},
        }), origin) == "think"
        assert_stream_end(output(message({
            "event": "content-block-finish",
            "index": 1,
            "content": {"type": "reasoning", "reasoning": "think"},
        }), origin))

        tool_start = message({
            "event": "content-block-start",
            "index": 2,
            "content": {"type": "tool_call_chunk", "id": "call-1"},
        })
        assert_atomic(output(tool_start, origin), identity_prefix, scope)
        tool_delta = message({
            "event": "content-block-delta",
            "index": 2,
            "delta": {
                "type": "block-delta",
                "fields": {
                    "type": "tool_call_chunk",
                    "id": "call-1",
                    "name": "lookup",
                    "args": '{"query":"value"}',
                },
            },
        })
        assert_atomic(output(tool_delta, origin), identity_prefix, scope)
        assert_atomic(output(message({
            "event": "content-block-finish",
            "index": 2,
            "content": {
                "type": "tool_call",
                "id": "call-1",
                "name": "lookup",
                "args": {"query": "value"},
            },
        }), origin), identity_prefix, scope)
        assert_atomic(output(message({
            "event": "content-block-finish",
            "index": 3,
            "content": {"type": "image", "url": "https://example.invalid/a.png"},
        }), origin), identity_prefix, scope)
        assert_atomic(
            output(message({"event": "message-finish", "usage": {}}), origin),
            identity_prefix,
            scope,
        )
        assert_atomic(
            output(message({"event": "error", "error": "failed"}), origin),
            identity_prefix,
            scope,
        )

        for tool_event in (
            {"event": "tool-started", "tool_call_id": "call-1", "name": "lookup"},
            {"event": "tool-output-delta", "tool_call_id": "call-1", "delta": "half"},
            {"event": "tool-finished", "tool_call_id": "call-1", "output": "done"},
            {"event": "tool-error", "tool_call_id": "call-1", "error": "failed"},
        ):
            assert_atomic(output(envelope("tools", tool_event), origin), identity_prefix, scope)
        for lifecycle_event in (
            {"event": "started", "graph_name": "worker"},
            {"event": "completed", "graph_name": "worker"},
            {"event": "failed", "graph_name": "worker"},
        ):
            assert_atomic(
                output(envelope("lifecycle", lifecycle_event), origin),
                identity_prefix,
                scope,
            )
        assert_atomic(output(envelope("values", {"answer": 42}), origin), identity_prefix, scope)
        assert_atomic(
            output(envelope("custom", {"progress": "working"}), origin),
            identity_prefix,
            scope,
        )
        assert_atomic(
            output(envelope("future-channel", {"future": True}), origin),
            identity_prefix,
            scope,
        )

        if "run_output" in namespace:
            for phase in ("start", "end", "error"):
                assert_atomic(namespace["run_output"]({
                    "type": "agent_shell.workflow_run",
                    "phase": phase,
                    "status": "failed" if phase == "error" else "completed",
                    "finish_reason": "error" if phase == "error" else "stop",
                    "error_code": "failure" if phase == "error" else "",
                }, origin), identity_prefix, scope)

    agent_output = runpy.run_path(
        str(source_root / "agent-components/agent-event-output/all-events/main.py")
    )["output"]
    subagent_name = 'Research <& "[child]">'
    subagent_origin = {
        **agent_origin,
        "subagent_profile_id": "subagent-1",
        "subagent_name": subagent_name,
    }
    subagent_value = agent_output(
        message({"event": "message-start", "id": "msg-subagent"}),
        subagent_origin,
    )
    assert f"<summary>{escape(f'Agent [{subagent_name}] · Message started')}</summary>" in subagent_value
    assert escape(main_agent_name) not in subagent_value.split("</summary>", 1)[0]
