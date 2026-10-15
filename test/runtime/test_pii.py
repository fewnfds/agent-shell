from __future__ import annotations

import asyncio
import json
from pathlib import Path
import runpy
import warnings
from html import unescape

import pytest
from langchain.agents.middleware.pii import PIIDetectionError
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import Field

from agent_shell.contracts import PIIBlock
from agent_shell.runtime.agent_compilation import assemble_agent_middleware, construct_agent
from agent_shell.runtime.capabilities.pii import materialize_pii_middleware
from agent_shell.runtime.output_projection import OutputProjector


class CaptureModel(FakeListChatModel):
    seen: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _agent(model, rules):
    block = PIIBlock(name="PII", rules=rules)
    middleware = assemble_agent_middleware(
        foundation=(), pii=materialize_pii_middleware(block.model_dump(mode="json")),
        subagent=None, summarization=None, patch_tool_calls=None, model_call_limit=None,
        tool_call_limit=None, tool_error_boundary=None, todo=None,
        model_request_settings=None, provider_error_boundary=None,
    )
    return construct_agent({"model": model, "middleware": middleware}, scope="main_agent", owner_id="main", owner_name="Main", subject="Main Agent", path="capability_refs")


def test_async_pii_input_tool_results_output_and_block() -> None:
    model = CaptureModel(responses=["reply to alice@example.com"])
    agent = _agent(model, [{"pii_type": "email", "apply_to_output": True, "apply_to_tool_results": True}])
    result = asyncio.run(agent.ainvoke({"messages": [
        HumanMessage(content="ask alice@example.com"),
        AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call"}]),
        ToolMessage(content="found alice@example.com", tool_call_id="call"),
    ]}))
    assert model.seen[0][0].content == "ask [REDACTED_EMAIL]"
    assert model.seen[0][-1].content == "found [REDACTED_EMAIL]"
    assert result["messages"][-1].content == "reply to [REDACTED_EMAIL]"

    blocked_model = CaptureModel(responses=["unused"])
    blocked = _agent(blocked_model, [{"pii_type": "access_code", "detector": r"code-\d+", "strategy": "block"}])
    with pytest.raises(PIIDetectionError):
        asyncio.run(blocked.ainvoke({"messages": [HumanMessage(content="code-222")]}))
    assert blocked_model.seen == []


def _events(agent):
    async def collect():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            stream = await agent.astream_events({"messages": [HumanMessage(content="reply")]}, version="v3")
        async with stream:
            return [event async for event in stream]

    return asyncio.run(collect())


@pytest.mark.parametrize("response", ["Email alice@example.com now.", "Please reply. " * 25 + "alice@example.com" + " Thank you." * 25])
def test_pii_official_v3_final_snapshot(response) -> None:
    agent = _agent(FakeListChatModel(responses=[response]), [{"pii_type": "email", "apply_to_output": True}])
    events = _events(agent)
    deltas = [event["params"]["data"][0] for event in events if event.get("method") == "messages" and event["params"]["data"][0].get("event") == "content-block-delta"]
    assert all("alice@example.com" not in delta["delta"].get("text", "") for delta in deltas)
    finished = [event["params"]["data"][0] for event in events if event.get("method") == "messages" and event["params"]["data"][0].get("event") == "content-block-finish"]
    expected = response.replace("alice@example.com", "[REDACTED_EMAIL]")
    assert finished[-1]["content"]["text"] == expected
    assert "alice@example.com" not in json.dumps(events, default=str)


@pytest.mark.parametrize(("response", "disable_streaming"), [
    ("Email alice@example.com now.", False),
    ("Please reply. " * 25 + "alice@example.com" + " Thank you." * 25, True),
])
def test_pii_output_templates_consume_finalized_text(response, disable_streaming) -> None:
    model = FakeListChatModel(responses=[response], disable_streaming=disable_streaming)
    events = _events(_agent(model, [{"pii_type": "email", "apply_to_output": True}]))
    expected = response.replace("alice@example.com", "[REDACTED_EMAIL]")
    text_events = [event for event in events if event.get("method") == "messages" and (
        not isinstance(event["params"]["data"][0], dict)
        or event["params"]["data"][0].get("event") in {"content-block-start", "content-block-delta", "content-block-finish"}
    )]
    templates = Path(__file__).parents[2] / "examples" / "agent-components" / "agent-event-output"
    server_events = [{**event, "params": {**event["params"], "data": {
        **event["params"]["data"][0], "metadata": event["params"]["data"][1],
    }}} if isinstance(event["params"]["data"][0], dict) else event for event in text_events]
    for transport_events in (text_events, server_events):
        for name in ("default", "assistant-text-only", "all-events"):
            output = runpy.run_path(str(templates / name / "main.py"))["output"]
            projector = OutputProjector(output)
            rendered = "".join(projector.render(event, {"agent_profile_id": "main", "main_agent_name": "Main"}) for event in transport_events)
            assert unescape(rendered).count(expected) == 1, name
