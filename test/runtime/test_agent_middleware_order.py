from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Annotated, ClassVar

from deepagents.middleware import UnsupportedContentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import HumanMessage
from langgraph.store.memory import InMemoryStore
from typing_extensions import NotRequired, TypedDict

from agent_shell.runtime import agent_builder, subagent_middleware, subagents
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_compilation import (
    MaterializedAgentResources,
    assemble_agent_middleware,
)
from agent_shell.runtime.capabilities.call_limits import (
    materialize_model_call_limit_middleware,
    materialize_tool_call_limit_middleware,
)
from agent_shell.runtime.state import AgentShellState
from agent_shell.validation.assembly import (
    ResolvedSubagent,
    ResolvedSubagentEdge,
    StaticAssembly,
)
from agent_shell.validation.models import ValidationReport


def _middleware(name: str, *, state_schema: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, tools=(), state_schema=state_schema)


def _resources(
    *,
    foundation: tuple[object, ...],
    todo: object,
    summarization: object,
    model_call_limit: object,
    tool_call_limit: object,
    retry: object,
    packages: tuple[object, ...],
    workspace: object,
) -> MaterializedAgentResources:
    return MaterializedAgentResources(
        model=object(),
        tool_choice="auto",
        response_format=None,
        model_settings={"temperature": 0},
        exception_retry=SimpleNamespace(after_provider_boundary=(retry,)),
        system_prompt=None,
        tools=(),
        foundation_middleware=foundation,
        todo_middleware=todo,
        summarization_middleware=summarization,
        model_call_limit_middleware=model_call_limit,
        tool_call_limit_middleware=tool_call_limit,
        package_middleware=packages,
        backend=object(),
        middleware_backend=object(),
        workspace=workspace,
    )


def test_main_agent_and_subagent_use_the_shell_owned_middleware_slots(
    tmp_path,
    monkeypatch,
) -> None:
    main_skill = _middleware("MainSkills")
    main_filesystem = _middleware("MainFilesystem")
    main_todo = _middleware("MainTodo")
    main_summarization = _middleware("MainSummarization")
    main_model_call_limit = _middleware("MainModelCallLimit")
    main_tool_call_limit = _middleware("MainToolCallLimit")
    main_retry = _middleware("MainRetry")
    main_packages = (
        _middleware("MainPackageOne", state_schema=object),
        _middleware("MainPackageTwo"),
    )
    main_resources = _resources(
        foundation=(main_skill, main_filesystem),
        todo=main_todo,
        summarization=main_summarization,
        model_call_limit=main_model_call_limit,
        tool_call_limit=main_tool_call_limit,
        retry=main_retry,
        packages=main_packages,
        workspace=SimpleNamespace(initial_files={"/seed.txt": "seed"}),
    )

    child_skill = _middleware("ChildSkills")
    child_filesystem = _middleware("ChildFilesystem")
    child_todo = _middleware("ChildTodo")
    child_summarization = _middleware("ChildSummarization")
    child_model_call_limit = _middleware("ChildModelCallLimit")
    child_tool_call_limit = _middleware("ChildToolCallLimit")
    child_retry = _middleware("ChildRetry")
    child_packages = (
        _middleware("ChildPackageOne"),
        _middleware("ChildPackageTwo"),
    )
    child_resources = _resources(
        foundation=(child_skill, child_filesystem),
        todo=child_todo,
        summarization=child_summarization,
        model_call_limit=child_model_call_limit,
        tool_call_limit=child_tool_call_limit,
        retry=child_retry,
        packages=child_packages,
        workspace=SimpleNamespace(initial_files={}),
    )

    child = ResolvedSubagent(
        key="child-id",
        component_name="Worker component",
        name="worker",
        description="Handles delegated work.",
        references={},
        blocks={},
        filesystem_mode="composite",
    )
    event_output = {
        "id": "55555555-5555-4555-8555-555555555555",
        "name": "Output",
        "python_package": {
            "folder": "55555555-5555-4555-8555-555555555555",
        },
    }
    assembly = StaticAssembly(
        main_agent={"id": "main-id", "name": "Main Agent"},
        references={
            "model-requirement": "model-requirement-id",
            "agent-event-output": "55555555-5555-4555-8555-555555555555",
        },
        blocks={
            "model-requirement": {"id": "model-requirement-id"},
            "agent-event-output": event_output,
            "subagent": {
                "instruction_override": None,
                "task_description_override": "Delegate work.",
            },
        },
        filesystem_mode="composite",
        subagents=(ResolvedSubagentEdge(target_key=child.key),),
        subagent_nodes={child.key: child},
    )
    validation = SimpleNamespace(
        resolve_main_agent=lambda *_args, **_kwargs: (
            ValidationReport(stage="request_assembly", issues=()),
            assembly,
        )
    )
    builder = AgentBuilder(
        SimpleNamespace(),
        python_packages_dir=tmp_path / "python-packages",
        data_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        skills_dir=tmp_path / "skills",
        validation=validation,
        provider_http_clients=SimpleNamespace(),
        store=InMemoryStore(),
    )

    def materialize(*_args, scope: str, **_kwargs):
        return child_resources if scope == "subagent" else main_resources

    monkeypatch.setattr(builder, "_materialize_agent_resources", materialize)
    monkeypatch.setattr(
        agent_builder.MiddlewarePackageRuntime,
        "from_assembly",
        classmethod(lambda _cls, *_args, **_kwargs: SimpleNamespace()),
    )

    main_patch = _middleware("MainPatch")
    main_tool_boundary = _middleware("MainToolBoundary")
    main_settings = _middleware("MainModelSettings")
    main_provider_boundary = _middleware("MainProviderBoundary")
    main_initial_files = _middleware("MainInitialFiles")
    child_patch = _middleware("ChildPatch")
    child_tool_boundary = _middleware("ChildToolBoundary")
    child_settings = _middleware("ChildModelSettings")
    child_provider_boundary = _middleware("ChildProviderBoundary")
    child_empty_prompt = _middleware("ChildEmptyPrompt")
    delegation = _middleware("SubAgentMiddleware")

    monkeypatch.setattr(
        agent_builder, "materialize_patch_tool_calls_middleware", lambda: main_patch
    )
    monkeypatch.setattr(
        agent_builder,
        "ToolErrorBoundaryMiddleware",
        lambda **_kwargs: main_tool_boundary,
    )
    monkeypatch.setattr(
        agent_builder,
        "make_model_request_settings_middleware",
        lambda **_kwargs: main_settings,
    )
    monkeypatch.setattr(
        agent_builder,
        "ProviderErrorBoundaryMiddleware",
        lambda **_kwargs: main_provider_boundary,
    )
    monkeypatch.setattr(
        agent_builder,
        "AgentInitialFilesMiddleware",
        lambda _files: main_initial_files,
    )
    monkeypatch.setattr(
        subagents, "materialize_patch_tool_calls_middleware", lambda: child_patch
    )
    monkeypatch.setattr(
        subagents, "ToolErrorBoundaryMiddleware", lambda **_kwargs: child_tool_boundary
    )
    monkeypatch.setattr(
        subagents,
        "make_model_request_settings_middleware",
        lambda **_kwargs: child_settings,
    )
    monkeypatch.setattr(
        subagents,
        "ProviderErrorBoundaryMiddleware",
        lambda **_kwargs: child_provider_boundary,
    )
    monkeypatch.setattr(
        subagents, "EmptySystemMessageMiddleware", lambda: child_empty_prompt
    )

    captured: dict[str, object] = {}

    def capture_subagent(*, subagents, middleware, **_kwargs):
        captured["subagent_specs"] = subagents
        captured["delegation_input"] = list(middleware)
        return delegation

    monkeypatch.setattr(
        subagent_middleware,
        "materialize_subagent_middleware",
        capture_subagent,
    )

    def capture_constructor(constructor, **_kwargs):
        captured["constructor"] = constructor
        return object()

    monkeypatch.setattr(agent_builder, "construct_agent", capture_constructor)

    asyncio.run(
        builder.build(
            "main-id",
            [{"role": "user", "content": "Hello"}],
        )
    )

    constructor = captured["constructor"]
    assert set(constructor) == {
        "model",
        "name",
        "state_schema",
        "context_schema",
        "store",
        "middleware",
    }
    assert constructor["state_schema"] is AgentShellState
    assert constructor["middleware"][:-1] == [
        main_skill,
        main_filesystem,
        delegation,
        main_summarization,
        main_patch,
        main_model_call_limit,
        main_tool_call_limit,
        main_tool_boundary,
        main_todo,
        main_settings,
        main_provider_boundary,
        main_retry,
        main_initial_files,
        *main_packages,
    ]
    assert isinstance(constructor["middleware"][-1], UnsupportedContentMiddleware)
    assert captured["delegation_input"][:-1] == [
        main_skill,
        main_filesystem,
        main_summarization,
        main_patch,
        main_model_call_limit,
        main_tool_call_limit,
        main_tool_boundary,
        main_todo,
        main_settings,
        main_provider_boundary,
        main_retry,
        main_initial_files,
        *main_packages,
    ]
    assert isinstance(captured["delegation_input"][-1], UnsupportedContentMiddleware)

    child_spec = captured["subagent_specs"][0]
    assert "permissions" not in child_spec
    assert "runnable" not in child_spec
    assert child_spec["middleware"][:-1] == [
        child_skill,
        child_filesystem,
        child_summarization,
        child_patch,
        child_model_call_limit,
        child_tool_call_limit,
        child_tool_boundary,
        child_todo,
        child_settings,
        child_provider_boundary,
        child_retry,
        *child_packages,
        child_empty_prompt,
    ]
    assert isinstance(child_spec["middleware"][-1], UnsupportedContentMiddleware)


def test_concurrent_agent_builds_keep_request_local_package_runtimes(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeToolRuntime:
        def __init__(self, label: str) -> None:
            self.label = label
            self.closed = False

        def tools_for(self, _owner_id: str):
            return (SimpleNamespace(name=f"{self.label}-tool"),)

        def close_sync(self) -> None:
            self.closed = True

        async def close(self) -> None:
            self.close_sync()

    class FakeMiddlewareRuntime:
        def __init__(self, label: str) -> None:
            self.label = label
            self.closed = False

        def middleware_for(self, _owner_id: str, *, context=None):
            del context
            return (_middleware(f"{self.label}-middleware"),)

        def close_sync(self) -> None:
            self.closed = True

        async def close(self) -> None:
            self.close_sync()

    def assembly(label: str) -> StaticAssembly:
        output_id = "55555555-5555-4555-8555-555555555555"
        return StaticAssembly(
            main_agent={"id": label, "name": label},
            references={},
            blocks={
                "agent-event-output": {
                    "id": output_id,
                    "name": "Output",
                    "python_package": {"folder": output_id},
                }
            },
            filesystem_mode="composite",
            subagents=(),
            subagent_nodes={},
        )

    tool_runtimes: dict[str, FakeToolRuntime] = {}
    middleware_runtimes: dict[str, FakeMiddlewareRuntime] = {}

    def make_tool_runtime(value, **_kwargs):
        label = str(value.main_agent["id"])
        runtime = FakeToolRuntime(label)
        tool_runtimes[label] = runtime
        return runtime

    def make_middleware_runtime(value, **_kwargs):
        label = str(value.main_agent["id"])
        runtime = FakeMiddlewareRuntime(label)
        middleware_runtimes[label] = runtime
        return runtime

    monkeypatch.setattr(
        agent_builder.ToolPackageRuntime,
        "from_assembly",
        classmethod(lambda _cls, value, **kwargs: make_tool_runtime(value, **kwargs)),
    )
    monkeypatch.setattr(
        agent_builder.MiddlewarePackageRuntime,
        "from_assembly",
        classmethod(
            lambda _cls, value, **kwargs: make_middleware_runtime(value, **kwargs)
        ),
    )

    builder = AgentBuilder(
        SimpleNamespace(),
        python_packages_dir=tmp_path / "python-packages",
        data_root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        skills_dir=tmp_path / "skills",
        validation=SimpleNamespace(),
        provider_http_clients=SimpleNamespace(),
        store=InMemoryStore(),
    )
    first_materializing = threading.Event()
    release_first = threading.Event()
    second_materialized = threading.Event()
    observed: dict[str, tuple[str, str, str]] = {}

    def materialize(
        *_args,
        owner_id: str,
        tool_runtime=None,
        middleware_runtime=None,
        mcp_runtime=None,
        **_kwargs,
    ) -> MaterializedAgentResources:
        if owner_id == "agent-a":
            first_materializing.set()
            assert release_first.wait(timeout=5)
        effective_tools = tool_runtime or getattr(builder, "_tool_runtime")
        effective_middleware = middleware_runtime or getattr(
            builder, "_middleware_runtime"
        )
        observed[owner_id] = (
            effective_tools.label,
            effective_middleware.label,
            mcp_runtime.label,
        )
        if owner_id == "agent-b":
            second_materialized.set()
        return MaterializedAgentResources(
            model=object(),
            tool_choice=None,
            response_format=None,
            model_settings={},
            exception_retry=None,
            system_prompt=None,
            tools=effective_tools.tools_for(owner_id),
            foundation_middleware=(),
            todo_middleware=None,
            summarization_middleware=None,
            model_call_limit_middleware=None,
            tool_call_limit_middleware=None,
            package_middleware=effective_middleware.middleware_for(owner_id),
            backend=None,
            middleware_backend=None,
            workspace=None,
        )

    monkeypatch.setattr(builder, "_materialize_agent_resources", materialize)
    monkeypatch.setattr(
        agent_builder,
        "materialize_patch_tool_calls_middleware",
        lambda: _middleware("Patch"),
    )
    monkeypatch.setattr(
        agent_builder,
        "ToolErrorBoundaryMiddleware",
        lambda **_kwargs: _middleware("ToolBoundary"),
    )
    monkeypatch.setattr(
        agent_builder,
        "ProviderErrorBoundaryMiddleware",
        lambda **_kwargs: _middleware("ProviderBoundary"),
    )
    def construct(constructor, **_kwargs):
        if constructor["name"] == "agent-a":
            raise RuntimeError("agent-a construction failed")
        return object()

    monkeypatch.setattr(agent_builder, "construct_agent", construct)

    async def scenario() -> None:
        first = asyncio.create_task(
            builder.build_resolved(
                assembly("agent-a"),
                [],
                mcp_runtime=SimpleNamespace(label="agent-a"),
            )
        )
        assert await asyncio.to_thread(first_materializing.wait, 5)
        second = asyncio.create_task(
            builder.build_resolved(
                assembly("agent-b"),
                [],
                mcp_runtime=SimpleNamespace(label="agent-b"),
            )
        )
        assert await asyncio.to_thread(second_materialized.wait, 5)
        release_first.set()
        failed_first, built_second = await asyncio.gather(
            first,
            second,
            return_exceptions=True,
        )
        assert isinstance(failed_first, RuntimeError)
        assert str(failed_first) == "agent-a construction failed"
        assert tool_runtimes["agent-a"].closed is True
        assert middleware_runtimes["agent-a"].closed is True
        assert built_second.tool_runtime.closed is False
        assert built_second.middleware_runtime.closed is False
        await built_second.tool_runtime.close()
        await built_second.middleware_runtime.close()

    asyncio.run(scenario())

    assert observed == {
        "agent-a": ("agent-a", "agent-a", "agent-a"),
        "agent-b": ("agent-b", "agent-b", "agent-b"),
    }


def test_optional_slots_are_physically_absent_but_content_filter_is_fixed() -> None:
    patch = _middleware("Patch")
    tool_boundary = _middleware("ToolBoundary")
    provider_boundary = _middleware("ProviderBoundary")

    middleware = assemble_agent_middleware(
        foundation=(),
        subagent=None,
        summarization=None,
        patch_tool_calls=patch,
        model_call_limit=None,
        tool_call_limit=None,
        tool_error_boundary=tool_boundary,
        todo=None,
        model_request_settings=None,
        provider_error_boundary=provider_boundary,
    )

    assert middleware[:-1] == [patch, tool_boundary, provider_boundary]
    assert isinstance(middleware[-1], UnsupportedContentMiddleware)


def test_fixed_content_filter_replaces_unsupported_user_media_for_one_model_call() -> None:
    class CaptureModel(FakeListChatModel):
        seen_messages: ClassVar[list[list[object]]] = []

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            type(self).seen_messages.append(list(messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    CaptureModel.seen_messages.clear()
    model = CaptureModel(responses=["ok"], profile={"image_inputs": False})
    middleware = assemble_agent_middleware(
        foundation=(),
        subagent=None,
        summarization=None,
        patch_tool_calls=_middleware("Patch"),
        model_call_limit=None,
        tool_call_limit=None,
        tool_error_boundary=_middleware("ToolBoundary"),
        todo=None,
        model_request_settings=None,
        provider_error_boundary=_middleware("ProviderBoundary"),
    )
    agent = create_agent(model=model, middleware=[middleware[-1]])
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Describe this image"},
            {"type": "image", "base64": "aGVsbG8=", "mime_type": "image/png"},
        ]
    )

    result = agent.invoke({"messages": [message]})

    assert result["messages"][0].content_blocks[1]["type"] == "image"
    model_message = CaptureModel.seen_messages[0][0]
    assert model_message.content_blocks[1]["type"] == "text"
    assert "does not support image content" in model_message.content_blocks[1]["text"]


def test_call_limit_materializers_preserve_official_configuration() -> None:
    model_limit = materialize_model_call_limit_middleware(
        {"run_limit": 4, "thread_limit": 12, "exit_behavior": "error"}
    )
    tool_limit = materialize_tool_call_limit_middleware(
        {
            "tool_name": "search",
            "run_limit": 2,
            "thread_limit": 6,
            "exit_behavior": "end",
        }
    )

    assert model_limit.run_limit == 4
    assert model_limit.thread_limit == 12
    assert model_limit.exit_behavior == "error"
    assert tool_limit.tool_name == "search"
    assert tool_limit.run_limit == 2
    assert tool_limit.thread_limit == 6
    assert tool_limit.exit_behavior == "end"


def test_task_description_keeps_shell_middleware_private_state_keys(
    monkeypatch,
) -> None:
    class ParentPackageState(TypedDict):
        inherited_private_value: Annotated[str, PrivateStateAttr]

    class PackageState(ParentPackageState):
        public_value: str
        private_value: NotRequired[Annotated[list[str], PrivateStateAttr]]

    captured: dict[str, object] = {}

    class CapturingSubAgentMiddleware:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deepagents.middleware.SubAgentMiddleware",
        CapturingSubAgentMiddleware,
    )

    result = subagent_middleware.materialize_subagent_middleware(
        backend=object(),
        subagents=[
            {
                "name": "worker",
                "description": "Handles delegated work.",
                "model": object(),
                "tools": [],
            }
        ],
        task_description="Delegate to {available_agents}.",
        middleware=(_middleware("Package", state_schema=PackageState),),
        state_schema=AgentShellState,
    )

    assert isinstance(result, CapturingSubAgentMiddleware)
    assert captured["task_description"] == "Delegate to {available_agents}."
    private_state_keys = captured["private_state_keys"]
    assert "private_value" in private_state_keys
    assert "inherited_private_value" in private_state_keys
    assert "jump_to" in private_state_keys
    assert "_summarization_event" in private_state_keys
    assert "public_value" not in private_state_keys
