from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Annotated

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.store.memory import InMemoryStore
from typing_extensions import TypedDict

from agent_shell.runtime import agent_builder, subagent_middleware
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_compilation import MaterializedAgentProfile
from agent_shell.runtime.context import WorkflowRuntimeContext
from agent_shell.runtime.run_identity import WorkflowRunIdentity
from agent_shell.runtime.state import AgentShellState
from agent_shell.validation.assembly import (
    ResolvedSubagent,
    ResolvedSubagentEdge,
    StaticAssembly,
)
from agent_shell.validation.models import ValidationReport

class _ToolCapableFakeModel(FakeListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _ScopeReadingMiddleware(AgentMiddleware):
    def before_agent(self, state, runtime):
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"private={len(state['messages'])};"
                        f"parent={len(state['workflow_state_snapshot']['agent_invocations'])};"
                        f"node={runtime.context.workflow_node_id};"
                        f"invocation={runtime.context.node_invocation_id}"
                    ),
                }
            ]
        }


def _middleware(name: str, *, state_schema: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, tools=(), state_schema=state_schema)


def _profile(
    *,
    core: object,
    extra: object,
    retry: object,
    packages: tuple[object, ...],
) -> MaterializedAgentProfile:
    return MaterializedAgentProfile(
        model=object(),
        model_provider="openai",
        model_name="test-model",
        tool_choice=None,
        response_format=None,
        model_settings={"temperature": 0},
        exception_retry=SimpleNamespace(after_provider_boundary=(retry,)),
        system_prompt=None,
        tools=(),
        middleware=(core,),
        package_middleware=packages,
        extra_middleware=(extra,),
        backend=object(),
        skill_sources=(),
        permissions=(),
        workspace=SimpleNamespace(initial_files={}),
    )


def test_custom_middleware_reads_private_agent_state_and_parent_workflow_snapshot() -> None:
    middleware = _ScopeReadingMiddleware()
    agent = create_deep_agent(
        model=_ToolCapableFakeModel(responses=["answer"]),
        middleware=[middleware],
        state_schema=AgentShellState,
    )
    context = WorkflowRuntimeContext.for_run(
        identity=WorkflowRunIdentity(
            request_id="request-1",
            lifecycle_id="lifecycle-1",
            run_id="run-1",
            workflow_id="workflow-1",
            workflow_name="Workflow",
            thread_id="thread-1",
        ),
    ).for_workflow_agent(
        workflow_node_id="agent-current",
        agent_profile_id="agent-id",
        node_invocation_id="invocation-current",
    )

    result = agent.invoke(
        {
            "messages": [],
            "workflow_state_snapshot": {
                "agent_invocations": {
                    "prior": {"workflow_node_id": "agent-prior"}
                }
            },
        },
        context=context,
    )

    assert result["messages"][0].content == (
        "private=0;parent=1;node=agent-current;invocation=invocation-current"
    )


def test_custom_package_middleware_is_the_shell_caller_tail_for_main_and_subagent(
    tmp_path,
    monkeypatch,
) -> None:
    main_core = _middleware("MainCore")
    main_extra = _middleware("MainBeforeAgent")
    main_retry = _middleware("MainRetry")
    main_packages = (
        _middleware("MainPackageOne", state_schema=object),
        _middleware("MainPackageTwo"),
    )
    child_core = _middleware("ChildCore")
    child_extra = _middleware("ChildBeforeAgent")
    child_retry = _middleware("ChildRetry")
    child_packages = (
        _middleware("ChildPackageOne"),
        _middleware("ChildPackageTwo"),
    )
    main_profile = _profile(
        core=main_core,
        extra=main_extra,
        retry=main_retry,
        packages=main_packages,
    )
    child_profile = _profile(
        core=child_core,
        extra=child_extra,
        retry=child_retry,
        packages=child_packages,
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
        disabled_capabilities=frozenset(),
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
        runtime_dir=tmp_path / "runtime",
        skills_dir=tmp_path / "skills",
        validation=validation,
        provider_http_clients=SimpleNamespace(),
        store=InMemoryStore(),
    )

    def materialize(*_args, scope: str, **_kwargs):
        return child_profile if scope == "subagent" else main_profile

    monkeypatch.setattr(builder, "_materialize_profile", materialize)
    middleware_runtime = SimpleNamespace()
    monkeypatch.setattr(
        agent_builder.MiddlewarePackageRuntime,
        "from_assembly",
        classmethod(lambda _cls, *_args, **_kwargs: middleware_runtime),
    )
    captured: dict[str, object] = {}

    def capture_constructor(constructor, **_kwargs):
        captured["constructor"] = constructor
        return object()

    monkeypatch.setattr(agent_builder, "construct_deep_agent", capture_constructor)

    delegation = _middleware("SubAgentMiddleware")

    def capture_delegation(*, middleware, **_kwargs):
        captured["delegation_input"] = tuple(middleware)
        return delegation

    monkeypatch.setattr(
        subagent_middleware,
        "make_subagent_middleware_override",
        capture_delegation,
    )

    asyncio.run(
        builder.build(
            "main-id",
            [{"role": "user", "content": "Hello"}],
        )
    )

    constructor = captured["constructor"]
    main_middleware = constructor["middleware"]
    child_middleware = constructor["subagents"][0]["middleware"]
    delegation_input = captured["delegation_input"]

    assert main_middleware[-2:] == list(main_packages)
    assert child_middleware[-2:] == list(child_packages)
    assert main_middleware.index(main_extra) < main_middleware.index(main_packages[0])
    assert child_middleware.index(child_extra) < child_middleware.index(child_packages[0])
    assert main_middleware.index(main_retry) < main_middleware.index(main_packages[0])
    assert child_middleware.index(child_retry) < child_middleware.index(child_packages[0])
    assert main_middleware.index(delegation) < main_middleware.index(main_packages[0])
    assert delegation_input[-2:] == main_packages


def test_task_description_override_keeps_shell_middleware_private_state_keys(
    monkeypatch,
) -> None:
    class PackageState(TypedDict):
        public_value: str
        private_value: Annotated[str, PrivateStateAttr]

    captured: dict[str, object] = {}

    class CapturingSubAgentMiddleware:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deepagents.middleware.SubAgentMiddleware",
        CapturingSubAgentMiddleware,
    )

    result = subagent_middleware.make_subagent_middleware_override(
        backend=object(),
        subagents=[
            {
                "name": "worker",
                "description": "Handles delegated work.",
                "runnable": object(),
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
    assert "jump_to" in private_state_keys
    assert "public_value" not in private_state_keys
