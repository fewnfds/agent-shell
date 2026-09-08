from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from agent_shell.command_packages import CommandPackageRuntime
from agent_shell.event_output_packages import EventOutputPackageRuntime
from agent_shell.middleware_packages.runtime import MiddlewareOwner, MiddlewarePackageRuntime
from agent_shell.python_packages.authoring import (
    BUILTIN_EXAMPLE_TEMPLATE_PREFIX,
    PythonPackageAuthoringService,
)
from agent_shell.runtime.output_projection import OutputProjector
from agent_shell.tool_packages import ToolOwner, ToolPackageRuntime


REPOSITORY = Path(__file__).parents[2]
EXAMPLES = REPOSITORY / "examples"
EXPECTED_EXAMPLES = {
    "agent-event-output": {
        "all-events",
        "assistant-text-only",
        "default",
    },
    "workflow-event-output": {
        "all-events",
        "default",
        "lifecycle-progress",
    },
    "command": {
        "agent-run-command",
        "runtime-context-command",
        "state-routing-command",
        "workflow-run-command",
    },
    "custom-tool": {"default"},
    "custom-middleware": {"agent-additional-prompt"},
}


def _service(tmp_path: Path) -> PythonPackageAuthoringService:
    return PythonPackageAuthoringService(
        templates_root=tmp_path / "templates",
        examples_root=EXAMPLES,
        instances_root=tmp_path / "instances",
        runtime_root=tmp_path / "runtime",
    )


def _catalog_by_key(
    service: PythonPackageAuthoringService,
    block_type: str,
) -> dict[str, dict[str, object]]:
    result = service.template_catalog(block_type)
    assert result["errors"] == {}
    return {str(item["key"]): item for item in result["catalog"]}


def _create_examples(
    service: PythonPackageAuthoringService,
    block_type: str,
) -> dict[str, tuple[str, dict[str, str]]]:
    catalog = _catalog_by_key(service, block_type)
    created: dict[str, tuple[str, dict[str, str]]] = {}
    for index, key in enumerate(sorted(EXPECTED_EXAMPLES[block_type]), start=1):
        catalog_key = f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{key}"
        owner_id = str(uuid4())
        reference, change = service.create(
            block_type,
            owner_id,
            f"{block_type} audit {index}",
            template_key=catalog_key,
            template_revision=str(catalog[catalog_key]["revision"]),
        )
        change.finalize()
        created[key] = (owner_id, reference)
    return created


def _event(method: str, data: object) -> dict[str, object]:
    return {
        "type": "event",
        "method": method,
        "params": {"namespace": ["audit:1"], "data": data},
    }


def test_all_builtin_examples_compile_and_belong_to_their_adapter_catalog(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    total = 0

    for block_type, expected_keys in EXPECTED_EXAMPLES.items():
        catalog = _catalog_by_key(service, block_type)
        assert set(catalog) == {
            f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{key}" for key in expected_keys
        }
        total += len(catalog)
        for key in expected_keys:
            folder = EXAMPLES / {
                "agent-event-output": "agent-components/agent-event-output",
                "workflow-event-output": "workflow-components/workflow-event-output",
                "command": "workflow-components/command",
                "custom-tool": "agent-components/custom-tool",
                "custom-middleware": "agent-components/custom-middleware",
            }[block_type] / key
            source = (folder / "main.py").read_text(encoding="utf-8")
            compile(source, str(folder / "main.py"), "exec")
            assert (folder / "requirements.txt").is_file()
            item = catalog[f"{BUILTIN_EXAMPLE_TEMPLATE_PREFIX}{key}"]
            assert item["folder"] == key
            assert isinstance(item["python_requirements"], list)

    assert total == 12


def test_event_output_examples_materialize_and_render_supported_events(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    instances = tmp_path / "instances"
    runtime_root = tmp_path / "runtime"
    agent_examples = _create_examples(service, "agent-event-output")
    workflow_examples = _create_examples(service, "workflow-event-output")

    agent_origin = {
        "graph_kind": "agent",
        "lifecycle_id": "lifecycle-1",
        "run_id": "agent-run-1",
        "thread_id": "agent-thread-1",
        "assistant_id": "assistant-1",
        "caller_run_id": "",
        "operation_id": "entry",
        "workflow_id": "",
        "workflow_name": "",
        "main_agent_id": "agent-1",
        "main_agent_name": "Writer",
        "agent_profile_id": "agent-1",
        "subagent_profile_id": "",
        "subagent_name": "",
    }
    text_delta = _event(
        "messages",
        {
            "event": "content-block-delta",
            "delta": {"type": "text-delta", "text": "hello"},
        },
    )
    reasoning_delta = _event(
        "messages",
        {
            "event": "content-block-delta",
            "delta": {"type": "reasoning-delta", "reasoning": "think"},
        },
    )
    text_start = _event(
        "messages",
        {
            "event": "content-block-start",
            "content": {"type": "text", "text": ""},
        },
    )
    agent_runtime = EventOutputPackageRuntime(
        "agent",
        request_id="builtin-agent-event-output-audit",
        packages_dir=instances,
        runtime_root=runtime_root,
    )
    for key, (owner_id, reference) in agent_examples.items():
        output = agent_runtime.output_for(key, owner_id, reference)
        segment_end = agent_runtime.segment_end_for(key, owner_id, reference)
        projector = OutputProjector(output, segment_end=segment_end)
        assert isinstance(projector.render(text_delta, agent_origin), str)
        if key in {"default", "assistant-text-only"}:
            assert projector.render(text_delta, agent_origin) == "hello"
            assert projector.render(_event("tools", {"event": "tool-finished"}), agent_origin) == ""
        else:
            assert "Agent [Writer] · Assistant text" in projector.render(
                text_start, agent_origin
            )
            assert projector.render(text_delta, agent_origin) == "hello"
            assert projector.render(reasoning_delta, agent_origin) == "think"
            for event in (
                _event("tools", {"event": "tool-finished", "output": "done"}),
                _event("lifecycle", {"event": "started", "graph_name": "Writer"}),
                _event("values", {"messages": []}),
                _event("custom", {"progress": 1}),
            ):
                rendered = projector.render(event, agent_origin)
                assert isinstance(rendered, str) and "Agent [Writer]" in rendered
            assert projector.render_segment_end(text_start, agent_origin).endswith(
                "</details>\n"
            )
    asyncio.run(agent_runtime.close())

    workflow_origin = {
        **agent_origin,
        "graph_kind": "workflow",
        "run_id": "workflow-run-1",
        "thread_id": "workflow-thread-1",
        "workflow_id": "workflow-1",
        "workflow_name": "Review Workflow",
        "main_agent_id": "",
        "main_agent_name": "",
        "agent_profile_id": "",
    }
    workflow_runtime = EventOutputPackageRuntime(
        "workflow",
        request_id="builtin-workflow-event-output-audit",
        packages_dir=instances,
        runtime_root=runtime_root,
    )
    custom = _event("custom", {"progress": "working"})
    run_event = {
        "type": "agent_shell.workflow_run",
        "phase": "start",
        "status": "running",
    }
    for key, (owner_id, reference) in workflow_examples.items():
        output = workflow_runtime.output_for(key, owner_id, reference)
        segment_end = workflow_runtime.segment_end_for(key, owner_id, reference)
        run_output = workflow_runtime.workflow_run_output_for(
            key, owner_id, reference
        )
        assert run_output is not None
        projector = OutputProjector(
            output,
            segment_end=segment_end,
            run_output=run_output,
        )
        rendered = projector.render(custom, workflow_origin)
        assert isinstance(rendered, str) and "Workflow" in rendered
        rendered_run = projector.render_run(run_event, workflow_origin)
        assert isinstance(rendered_run, str) and "Workflow" in rendered_run
        if key == "all-events":
            assert "Workflow [Review Workflow] · Custom event" in rendered
            assert "Workflow [Review Workflow] · Run started" in rendered_run
            assert projector.render_segment_end(text_start, workflow_origin).endswith(
                "</details>\n"
            )
    asyncio.run(workflow_runtime.close())


def test_command_tool_and_middleware_examples_materialize_through_runtime(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    instances = tmp_path / "instances"
    runtime_root = tmp_path / "runtime"

    command_examples = _create_examples(service, "command")
    command_runtime = CommandPackageRuntime(
        request_id="builtin-command-audit",
        packages_dir=instances,
        runtime_root=runtime_root,
    )
    for key, (owner_id, reference) in command_examples.items():
        command = command_runtime.command_for(key, owner_id, reference)
        assert inspect.iscoroutinefunction(command)
        assert list(inspect.signature(command).parameters) == ["state", "runtime"]
    asyncio.run(command_runtime.close())

    tool_owner_id, tool_reference = _create_examples(service, "custom-tool")["default"]
    tool_runtime = ToolPackageRuntime(
        request_id="builtin-tool-audit",
        owners=[
            ToolOwner(
                "agent-1",
                ({"id": tool_owner_id, "python_package": tool_reference},),
            )
        ],
        packages_dir=instances,
        runtime_root=runtime_root,
    )
    tools = tool_runtime.tools_for("agent-1")
    assert len(tools) == 1
    assert tools[0].name == "word_count"
    assert tools[0].invoke({"text": "one two three"}) == 3
    asyncio.run(tool_runtime.close())

    middleware_owner_id, middleware_reference = _create_examples(
        service, "custom-middleware"
    )["agent-additional-prompt"]
    middleware_runtime = MiddlewarePackageRuntime(
        request_id="builtin-middleware-audit",
        owners=[
            MiddlewareOwner(
                id="agent-1",
                type="main_agent",
                name="Writer",
                packages=((middleware_owner_id, middleware_reference),),
            )
        ],
        packages_dir=instances,
        runtime_root=runtime_root,
    )
    middleware = middleware_runtime.middleware_for(
        "agent-1",
        context={"backend": object(), "scope": "main_agent"},
    )
    assert len(middleware) == 1
    assert isinstance(middleware[0], AgentMiddleware)
    update = asyncio.run(
        middleware[0].abefore_agent(
            {"messages": [{"role": "user", "content": "hello"}]},
            Runtime(context={}),
        )
    )
    assert update is not None
    marker = f"_agent_shell_aap_{middleware_owner_id.replace('-', '_')}_initialized"
    assert update[marker] is True
    assert asyncio.run(
        middleware[0].abefore_agent(
            {"messages": [], marker: True},
            Runtime(context={}),
        )
    ) is None
    asyncio.run(middleware_runtime.close())
