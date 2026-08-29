from types import SimpleNamespace

from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import omit_payload
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from langgraph.store.memory import InMemoryStore

from agent_shell.capability_manifest import DEFAULT_MIDDLEWARE_CAPABILITY_TYPES
from agent_shell.runtime import agent_builder, deepagents_harness
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.agent_compilation import enable_deepagents_trace_inputs
from agent_shell.storage.environment import EnvironmentSnapshot
from agent_shell.storage.model_connections import ModelResourceSnapshot


def _input_omitting_deepagents_middleware():
    backend = StateBackend()
    return [
        FilesystemMiddleware(backend=backend),
        SkillsMiddleware(backend=backend, sources=[]),
        SummarizationMiddleware(
            FakeListChatModel(responses=["summary"]),
            backend=backend,
        ),
        SubAgentMiddleware(
            backend=backend,
            subagents=[
                {
                    "name": "worker",
                    "description": "Handles delegated work.",
                    "runnable": RunnableLambda(lambda state: state),
                }
            ],
        ),
        PatchToolCallsMiddleware(),
    ]


def test_workflow_debug_restores_deep_agents_inputs_per_compilation() -> None:
    regular = _input_omitting_deepagents_middleware()
    debug = _input_omitting_deepagents_middleware()

    enable_deepagents_trace_inputs(debug, debug_capture=True)

    assert all(
        item.trace_policy.process_inputs is omit_payload for item in regular
    )
    for item in debug:
        process_inputs = item.trace_policy.process_inputs
        assert process_inputs is not None
        assert process_inputs(
            {
                "state": {
                    "messages": [{"role": "user", "content": "debug body"}],
                    "credential": "credential-sentinel",
                }
            }
        ) == {
            "state": {
                "messages": [{"role": "user", "content": "debug body"}],
                "credential": "[REDACTED]",
            }
        }
    assert PatchToolCallsMiddleware.trace_policy.process_inputs is omit_payload


def test_harness_profile_registration_uses_configured_model_identity(
    monkeypatch,
) -> None:
    import deepagents

    registered = []
    monkeypatch.setattr(deepagents_harness, "_registered_keys", set())
    monkeypatch.setattr(
        deepagents,
        "register_harness_profile",
        lambda key, profile: registered.append((key, profile)),
    )

    deepagents_harness.ensure_agent_shell_harness_profiles(
        provider="openai",
        model="organization/model:revision",
    )
    deepagents_harness.ensure_agent_shell_harness_profiles(
        provider="openai",
        model="organization/model:revision",
    )

    assert {key for key, _profile in registered} == {
        "openai",
        "openai:organization/model:revision",
    }
    assert len(registered) == 2
    assert all(
        profile.general_purpose_subagent.enabled is False
        for _key, profile in registered
    )


def test_agent_builder_disabled_capabilities_override_deep_agents_default_stack(
    tmp_path,
    monkeypatch,
) -> None:
    import deepagents.graph

    workspace = SimpleNamespace(initial_files={})
    monkeypatch.setattr(
        agent_builder,
        "_build_chat_model",
        lambda _block, _credential, _http_clients: object(),
    )
    monkeypatch.setattr(
        agent_builder,
        "build_deepagents_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(
            backend=object(),
            middleware=(),
            initial_files={},
            skill_sources=(),
            permissions=(),
            workspace=workspace,
        ),
    )
    builder = AgentBuilder(
        SimpleNamespace(resolve_model=lambda _model_id: None),
        python_packages_dir=tmp_path / "python-packages",
        runtime_dir=tmp_path / "runtime",
        skills_dir=tmp_path / "skills",
        validation=object(),
        provider_http_clients=object(),
        store=InMemoryStore(),
        model_resources=ModelResourceSnapshot.capture(
            [
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "name": "Harness model",
                    "provider": "openai",
                    "base_url": "https://provider.example/v1",
                    "credential": None,
                    "model": "gpt-5.3-codex",
                    "provider_settings": {},
                    "tool_choice": None,
                    "response_format": None,
                    "model_settings": {},
                }
            ],
            EnvironmentSnapshot.capture({}),
            {
                "33333333-3333-4333-8333-333333333333": {
                    "11111111-1111-4111-8111-111111111111": (
                        "22222222-2222-4222-8222-222222222222"
                    )
                }
            },
        ),
        repository_id="33333333-3333-4333-8333-333333333333",
    )
    profile = builder._materialize_profile(
        {
            "model-requirement": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "filesystem": "filesystem-id",
            "filesystem-tools": "filesystem-tools-id",
        },
        {
            "model-requirement": {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Harness requirement",
                "description": "Use the harness model.",
            },
            "filesystem": {"id": "filesystem-id", "name": "Workspace"},
            "filesystem-tools": {"id": "filesystem-tools-id", "name": "Workspace tools"},
        },
        filesystem_mode="composite",
        scope="main_agent",
        owner_id="main-id",
        owner_name="Main Agent",
        disabled_capabilities=DEFAULT_MIDDLEWARE_CAPABILITY_TYPES,
    )
    replacements = [*profile.middleware, *profile.extra_middleware]
    replacement_types = {item.name: type(item) for item in replacements}

    captured: dict[str, object] = {}

    class _CapturedGraph:
        def with_config(self, _config):
            return self

    def capture_create_agent(*_args, **kwargs):
        captured["middleware"] = kwargs["middleware"]
        return _CapturedGraph()

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr(deepagents.graph, "create_agent", capture_create_agent)
    deepagents_harness.ensure_agent_shell_harness_profiles(
        provider="openai",
        model="gpt-5.3-codex",
    )
    deepagents.graph.create_deep_agent(
        model="openai:gpt-5.3-codex",
        middleware=replacements,
    )

    final_by_name = {
        item.name: item for item in captured["middleware"]
    }
    assert set(replacement_types) == {
        "TodoListMiddleware",
        "SummarizationMiddleware",
        "AnthropicPromptCachingMiddleware",
    }
    assert {
        name: type(final_by_name[name]) for name in replacement_types
    } == replacement_types
