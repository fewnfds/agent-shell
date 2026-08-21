from types import SimpleNamespace

from langgraph.store.memory import InMemoryStore

from agent_shell.capability_manifest import DEFAULT_MIDDLEWARE_CAPABILITY_TYPES
from agent_shell.runtime import agent_builder, deepagents_harness
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.storage.environment import EnvironmentSnapshot
from agent_shell.storage.model_connections import ModelResourceSnapshot


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
            )
        },
        {
            "model-requirement": {
                "id": "11111111-1111-4111-8111-111111111111",
                "name": "Harness requirement",
                "description": "Use the harness model.",
            }
        },
        filesystem_mode="default-shared",
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
