from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import ClassVar

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from agent_shell.contracts import FilesystemBlock, FilesystemToolsBlock, SkillBlock
from agent_shell.runtime.agent_compilation import (
    assemble_agent_middleware,
    materialize_patch_tool_calls_middleware,
)
from agent_shell.runtime.capabilities import build_deepagents_capabilities
from agent_shell.runtime.context import AgentRuntimeContext
from agent_shell.runtime.limits import (
    ProviderErrorBoundaryMiddleware,
    ToolErrorBoundaryMiddleware,
)
from agent_shell.runtime.model_call_archive import ModelCallArchiveMiddleware
from agent_shell.storage.environment import EnvironmentSnapshot
from agent_shell.storage.model_call_archive import ModelCallArchive


def _model_request() -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(
            context=AgentRuntimeContext(
                request_id="request-1",
                lifecycle_id="lifecycle-1",
            ),
            execution_info=SimpleNamespace(
                run_id="run-1",
                thread_id="thread-1",
                task_id="task-1",
                node_attempt=1,
            ),
            server_info=None,
        ),
        model=SimpleNamespace(model_name="gpt-test"),
        system_message=None,
        messages=[],
        tools=[],
        tool_choice=None,
        model_settings={"temperature": 0},
    )


def test_archive_projects_inline_binary_and_round_trips(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    archive.append("lifecycle-1", {"model": {"name": "gpt-test"}})
    archive.append(
        "lifecycle-1",
        {
            "request": {
                "messages": [
                    {
                        "type": "image",
                        "base64": "a" * 5000,
                        "mime_type": "image/png",
                    }
                ]
            }
        },
    )

    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert "gpt-test" in text
    assert "<omitted 5000 chars>" in text
    assert "a" * 100 not in text

    archive.discard("lifecycle-1")
    assert archive.content("lifecycle-1") is None


def test_archive_counts_model_requests_by_run(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    archive.append("lifecycle-1", {"run_id": "run-1"})
    archive.append("lifecycle-1", {"run_id": "run-1"})
    archive.append("lifecycle-1", {"run_id": "run-2"})
    archive.append("lifecycle-1", {})

    assert archive.run_request_counts("lifecycle-1") == {
        "run-1": 2,
        "run-2": 1,
    }


def test_archive_redacts_secret_before_json_escaping(tmp_path) -> None:
    secret = 'part"one\npart-two'
    environment = EnvironmentSnapshot.capture({"MODEL_CREDENTIAL": secret})
    archive = ModelCallArchive(
        tmp_path / "model-calls",
        redact_secret_text=environment.redact_secret_text,
    )

    archive.append(
        "lifecycle-1",
        {"request": {"messages": [{"content": f"token={secret}"}]}},
    )

    content = archive.content("lifecycle-1")
    assert content is not None
    record = json.loads(content)
    assert record["request"]["messages"][0]["content"] == "token=[REDACTED]"


@pytest.mark.parametrize("secret", ["12345", "1", "true", "null", "\\n"])
def test_archive_secret_projection_preserves_json_values(tmp_path, secret: str) -> None:
    environment = EnvironmentSnapshot.capture({"MODEL_CREDENTIAL": secret})
    archive = ModelCallArchive(
        tmp_path / "model-calls",
        redact_secret_text=environment.redact_secret_text,
    )
    archive.append(
        "lifecycle",
        {
            "run_id": "run",
            "duration_ms": 12345,
            "node_attempt": 1,
            "response": None,
            "has_structured_response": True,
            "request": {"content": f"token={secret}", "text": "first\nsecond"},
        },
    )

    content = archive.content("lifecycle")
    assert content is not None
    record = json.loads(content)
    assert record["duration_ms"] == 12345
    assert record["node_attempt"] == 1
    assert record["response"] is None
    assert record["has_structured_response"] is True
    assert record["request"] == {
        "content": "token=[REDACTED]",
        "text": "first\nsecond",
    }
    assert archive.run_request_counts("lifecycle") == {"run": 1}


def test_model_call_archive_middleware_records_attempt_identity(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    middleware = ModelCallArchiveMiddleware(archive=archive)
    request = _model_request()
    response = SimpleNamespace(result=[], structured_response=None)

    returned = middleware.wrap_model_call(request, lambda _request: response)

    assert returned is response
    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert '"status":"succeeded"' in text
    assert '"run_id":"run-1"' in text
    assert '"task_id":"task-1"' in text
    assert '"name":"gpt-test"' in text


def test_model_call_archive_middleware_records_failed_attempt(tmp_path) -> None:
    archive = ModelCallArchive(tmp_path / "model-calls")
    middleware = ModelCallArchiveMiddleware(archive=archive)

    def fail(_request):
        raise RuntimeError("provider rejected the request")

    with pytest.raises(RuntimeError):
        middleware.wrap_model_call(_model_request(), fail)

    content = archive.content("lifecycle-1")
    assert content is not None
    text = content.decode("utf-8")
    assert '"status":"failed"' in text
    assert "provider rejected the request" in text


def test_archive_records_the_final_request_after_skills_and_custom_middleware(
    tmp_path,
) -> None:
    class CaptureModel(FakeListChatModel):
        seen_messages: ClassVar[list[list[object]]] = []

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            type(self).seen_messages.append(list(messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    class RouteModel(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            return await handler(request.override(model=routed_model))

    package_name = "Archive skills"
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / package_name / "outline"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: outline\ndescription: Outline a document.\n---\n",
        encoding="utf-8",
    )
    capabilities = build_deepagents_capabilities(
        FilesystemBlock.model_validate({"name": "Workspace"}),
        SkillBlock.model_validate(
            {"name": package_name, "skill_package": {"folder": package_name}}
        ),
        filesystem_tools=FilesystemToolsBlock.model_validate({"name": "File tools"}),
        filesystem_mode="composite",
        skills_dir=skills_dir,
    )
    CaptureModel.seen_messages.clear()
    routed_model = CaptureModel(responses=["ok"], profile={"image_inputs": False})
    archive = ModelCallArchive(tmp_path / "model-calls")
    middleware = assemble_agent_middleware(
        foundation=capabilities.middleware,
        subagent=None,
        summarization=None,
        patch_tool_calls=materialize_patch_tool_calls_middleware(),
        model_call_limit=None,
        tool_call_limit=None,
        tool_error_boundary=ToolErrorBoundaryMiddleware(),
        todo=None,
        model_request_settings=None,
        provider_error_boundary=ProviderErrorBoundaryMiddleware(),
        package=(RouteModel(),),
        model_call_archive=ModelCallArchiveMiddleware(archive=archive),
    )
    agent = create_agent(
        model=FakeListChatModel(responses=["unused"]),
        middleware=middleware,
        context_schema=AgentRuntimeContext,
    )
    asyncio.run(
        agent.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=[
                            {"type": "text", "text": "Outline this image"},
                            {"type": "image", "base64": "aGVsbG8=", "mime_type": "image/png"},
                        ]
                    )
                ]
            },
            context=AgentRuntimeContext(request_id="request-1", lifecycle_id="lifecycle-1"),
        )
    )

    content = archive.content("lifecycle-1")
    assert content is not None
    record = json.loads(content)
    sent_messages = CaptureModel.seen_messages[0]
    assert record["model"]["class"] == "CaptureModel"
    assert record["request"]["system_message"]["content"] == sent_messages[0].content
    assert "outline" in sent_messages[0].text
    assert record["request"]["messages"][0]["content"] == sent_messages[1].content
    assert "does not support image content" in str(sent_messages[1].content)
    assert "read_file" in {tool["name"] for tool in record["request"]["tools"]}
    assert record["response"]["messages"][0]["content"] == "ok"
