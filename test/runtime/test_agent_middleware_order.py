from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Annotated

from langchain.agents.middleware.types import PrivateStateAttr
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
    prompt_caching: object,
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
        prompt_caching_middleware=prompt_caching,
        package_middleware=packages,
        backend=object(),
        middleware_backend=object(),
        workspace=workspace,
    )


def test_main_and_child_use_the_shell_owned_middleware_slots(
    tmp_path,
    monkeypatch,
) -> None:
    main_skill = _middleware("MainSkills")
    main_filesystem = _middleware("MainFilesystem")
    main_todo = _middleware("MainTodo")
    main_summarization = _middleware("MainSummarization")
    main_model_call_limit = _middleware("MainModelCallLimit")
    main_tool_call_limit = _middleware("MainToolCallLimit")
    main_prompt_caching = _middleware("MainPromptCaching")
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
        prompt_caching=main_prompt_caching,
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
    child_prompt_caching = _middleware("ChildPromptCaching")
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
        prompt_caching=child_prompt_caching,
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
        agent_builder, "ToolErrorBoundaryMiddleware", lambda: main_tool_boundary
    )
    monkeypatch.setattr(
        agent_builder,
        "make_model_request_settings_middleware",
        lambda **_kwargs: main_settings,
    )
    monkeypatch.setattr(
        agent_builder, "ProviderErrorBoundaryMiddleware", lambda: main_provider_boundary
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
        subagents, "ToolErrorBoundaryMiddleware", lambda: child_tool_boundary
    )
    monkeypatch.setattr(
        subagents,
        "make_model_request_settings_middleware",
        lambda **_kwargs: child_settings,
    )
    monkeypatch.setattr(
        subagents, "ProviderErrorBoundaryMiddleware", lambda: child_provider_boundary
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
    assert constructor["middleware"] == [
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
        main_prompt_caching,
    ]
    assert captured["delegation_input"] == [
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
        main_prompt_caching,
    ]

    child_spec = captured["subagent_specs"][0]
    assert "permissions" not in child_spec
    assert "runnable" not in child_spec
    assert child_spec["middleware"] == [
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
        child_prompt_caching,
    ]


def test_optional_slots_are_physically_absent() -> None:
    foundation = _middleware("Filesystem")
    patch = _middleware("Patch")
    tool_boundary = _middleware("ToolBoundary")
    provider_boundary = _middleware("ProviderBoundary")

    middleware = assemble_agent_middleware(
        foundation=(foundation,),
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

    assert middleware == [foundation, patch, tool_boundary, provider_boundary]


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
