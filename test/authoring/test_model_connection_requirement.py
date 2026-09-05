from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_shell.api.model_connections import build_model_connection_router
from agent_shell.configuration.bundles.contracts import BundleRoot
from agent_shell.configuration.bundles.exporting import ConfigurationBundleExporter
from agent_shell.configuration.bundles.planning import BundleImportPlanner
from agent_shell.configuration.bundles.archive import parse_bundle
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    API_SERVER_ENVIRONMENT_OWNER,
    EnvironmentSnapshot,
    InstanceEnvironmentStore,
    MODEL_CONNECTION_ENVIRONMENT_OWNER,
    parse_environment_text,
)
from agent_shell.storage.model_connections import ModelResourceSnapshot, ModelResourceStore
from agent_shell.provider_secrets import ProviderSecretResolver
import agent_shell.storage.model_connections as model_connection_storage
from agent_shell.runtime import agent_builder as agent_builder_module
from agent_shell.runtime.agent_builder import AgentBuilder
from agent_shell.runtime.errors import AgentRuntimeError
from langgraph.store.memory import InMemoryStore


def connection_payload(name: str = "Local") -> dict[str, object]:
    return {
        "name": name,
        "provider": "openai",
        "base_url": "https://api.example.com/v1",
        "credential": "do-not-export-this-secret",
        "model": "gpt-local",
        "provider_settings": {},
        "tool_choice": None,
        "response_format": None,
        "model_settings": {},
    }


def runtime_builder(
    tmp_path: Path,
    repository: FileConfigRepository,
    resources: ModelResourceStore,
    *,
    model_resources: ModelResourceSnapshot | None = None,
) -> AgentBuilder:
    return AgentBuilder(
        ProviderSecretResolver(repository, resources),
        python_packages_dir=tmp_path / "python-packages",
        runtime_dir=tmp_path / "runtime",
        skills_dir=tmp_path / "skills",
        validation=object(),
        provider_http_clients=object(),
        store=InMemoryStore(),
        model_resources=model_resources or resources.snapshot(),
        repository_id=repository.repository_id,
    )


def test_model_connection_is_instance_private_and_secret_is_write_only(tmp_path: Path) -> None:
    resources = ModelResourceStore(tmp_path)
    connection = resources.save_connection(
        "11111111-1111-4111-8111-111111111111",
        connection_payload(),
    )

    assert connection["credential"] == {"status": "masked"}
    assert "do-not-export-this-secret" not in str(connection)
    assert resources.resolve_connection(connection["id"])["credential"] == "do-not-export-this-secret"
    assert not (tmp_path / "config_repos").exists()


def test_saved_connection_resolves_masked_catalog_credential(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    connection = resources.save_connection(
        "44444444-4444-4444-8444-444444444444",
        connection_payload(),
    )

    resolver = ProviderSecretResolver(repository, resources)
    assert resolver.resolve_request(
        None,
        provider="openai",
        block_id=connection["id"],
        base_url="https://api.example.com/v1",
    ) == "do-not-export-this-secret"


def test_model_connection_save_restores_env_when_document_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resources = ModelResourceStore(tmp_path)
    connection_id = "55555555-5555-4555-8555-555555555555"
    resources.save_connection(connection_id, connection_payload())
    yaml_path = tmp_path / "config" / "model-connections" / f"{connection_id}.yaml"
    env_path = tmp_path / "config" / "agent-shell.env"
    old_yaml = yaml_path.read_text(encoding="utf-8")
    old_env = env_path.read_text(encoding="utf-8")
    original_write = model_connection_storage.write_text_atomic

    def fail_on_document(path: Path, text: str) -> None:
        if path == yaml_path and "Changed" in text:
            raise OSError("injected document write failure")
        original_write(path, text)

    monkeypatch.setattr(model_connection_storage, "write_text_atomic", fail_on_document)
    changed = {**connection_payload("Changed"), "credential": "replacement-secret"}
    try:
        resources.save_connection(connection_id, changed)
    except OSError:
        pass
    else:
        raise AssertionError("save should surface the document write failure")
    assert yaml_path.read_text(encoding="utf-8") == old_yaml
    assert env_path.read_text(encoding="utf-8") == old_env


def test_standard_dotenv_codec_round_trips_model_credential_and_preserves_api_key(
    tmp_path: Path,
) -> None:
    assert parse_environment_text(
        "# Standard dotenv comments and blank lines are accepted.\n\n"
        "AGENT_SHELL_API_KEY=old-key\n"
        "AGENT_SHELL_API_KEY=local-api-key\n"
    ) == {"AGENT_SHELL_API_KEY": "local-api-key"}
    mutations = ConfigurationMutationCoordinator()
    environment = InstanceEnvironmentStore(
        tmp_path / "config" / "agent-shell.env",
        mutations=mutations,
    )
    environment.patch(
        API_SERVER_ENVIRONMENT_OWNER,
        set_values={"AGENT_SHELL_API_KEY": "local-api-key"},
    )
    resources = ModelResourceStore(
        tmp_path,
        environment=environment,
        mutations=mutations,
    )
    credential = "  single' double\" slash\\ tab\t cr\r lf\nUnicode-密钥  "
    payload = {**connection_payload(), "credential": credential}

    connection = resources.save_connection(
        "99999999-9999-4999-8999-999999999999",
        payload,
    )

    assert resources.resolve_connection(connection["id"])["credential"] == credential
    assert environment.get("AGENT_SHELL_API_KEY") == "local-api-key"
    parsed = parse_environment_text(
        environment.path.read_text(encoding="utf-8")
    )
    assert parsed["AGENT_SHELL_API_KEY"] == "local-api-key"
    assert credential in parsed.values()
    assert environment.path.read_text(encoding="utf-8").startswith(
        "AGENT_SHELL_API_KEY=local-api-key\n"
    )


def test_connection_change_without_credential_removes_orphan_secret(
    tmp_path: Path,
) -> None:
    mutations = ConfigurationMutationCoordinator()
    environment = InstanceEnvironmentStore(
        tmp_path / "config" / "agent-shell.env",
        mutations=mutations,
    )
    resources = ModelResourceStore(
        tmp_path,
        environment=environment,
        mutations=mutations,
    )
    connection_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    resources.save_connection(connection_id, connection_payload())

    changed = {
        **connection_payload("Changed endpoint"),
        "base_url": "https://other.example/v1",
        "credential": None,
    }
    saved = resources.save_connection(connection_id, changed)

    assert saved["credential"] == {"status": "missing"}
    assert resources.resolve_connection(connection_id)["credential"] is None
    assert environment.owned_values(
        MODEL_CONNECTION_ENVIRONMENT_OWNER
    ) == {}


def test_delete_connection_rolls_back_document_credential_and_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = ModelResourceStore(tmp_path)
    connection_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    repository_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    requirement_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    resources.save_connection(connection_id, connection_payload())
    resources.set_binding(repository_id, requirement_id, connection_id)
    original_write = model_connection_storage.write_text_atomic
    failed = False

    def fail_bindings_once(path: Path, text: str) -> None:
        nonlocal failed
        if path == resources.bindings_path and not failed:
            failed = True
            raise OSError("injected binding write failure")
        original_write(path, text)

    monkeypatch.setattr(
        model_connection_storage,
        "write_text_atomic",
        fail_bindings_once,
    )

    with pytest.raises(OSError, match="binding write failure"):
        resources.delete_connection(connection_id)

    assert resources.get_connection(connection_id) is not None
    assert (
        resources.resolve_connection(connection_id)["credential"]
        == "do-not-export-this-secret"
    )
    assert resources.get_binding(repository_id, requirement_id) == connection_id


def test_delete_connection_removes_all_scoped_bindings_and_credential(
    tmp_path: Path,
) -> None:
    mutations = ConfigurationMutationCoordinator()
    environment = InstanceEnvironmentStore(
        tmp_path / "config" / "agent-shell.env",
        mutations=mutations,
    )
    resources = ModelResourceStore(
        tmp_path,
        environment=environment,
        mutations=mutations,
    )
    connection_id = "12121212-1212-4121-8121-121212121212"
    other_connection_id = "34343434-3434-4343-8343-343434343434"
    repository_ids = (
        "56565656-5656-4565-8565-565656565656",
        "78787878-7878-4787-8787-787878787878",
    )
    requirement_ids = (
        "90909090-9090-4909-8909-909090909090",
        "abababab-abab-4aba-8aba-abababababab",
    )
    resources.save_connection(connection_id, connection_payload())
    resources.save_connection(
        other_connection_id,
        connection_payload("Other connection"),
    )
    for repository_id, requirement_id in zip(
        repository_ids,
        requirement_ids,
        strict=True,
    ):
        resources.set_binding(repository_id, requirement_id, connection_id)
    resources.set_binding(
        repository_ids[0],
        "cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd",
        other_connection_id,
    )

    assert resources.delete_connection(connection_id) is True

    assert resources.get_connection(connection_id) is None
    remaining_credentials = environment.owned_values(
        MODEL_CONNECTION_ENVIRONMENT_OWNER
    )
    assert list(remaining_credentials.values()) == ["do-not-export-this-secret"]
    for repository_id, requirement_id in zip(
        repository_ids,
        requirement_ids,
        strict=True,
    ):
        assert resources.get_binding(repository_id, requirement_id) is None
    assert resources.get_binding(
        repository_ids[0],
        "cdcdcdcd-cdcd-4cdc-8cdc-cdcdcdcdcdcd",
    ) == other_connection_id


def test_model_requirement_binding_is_scoped_and_reports_unbound(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    blocks = BlockStore(repository)
    resources = ModelResourceStore(tmp_path)
    requirement_id = repository.new_configuration_id()
    blocks.save_block(
        "model-requirement",
        requirement_id,
        {"name": "Reasoning", "description": "Needs a reasoning-capable model."},
    )
    connection = resources.save_connection(
        "22222222-2222-4222-8222-222222222222",
        connection_payload(),
    )

    app = FastAPI()
    app.include_router(build_model_connection_router(repository, blocks, resources))
    client = TestClient(app)
    requirement = client.get("/agent-shell/api/model-requirements").json()[0]
    assert requirement["binding"] is None

    bound = client.put(
        f"/agent-shell/api/model-requirements/{requirement_id}/binding",
        json={"connection_id": connection["id"]},
    )
    assert bound.status_code == 200
    assert bound.json()["binding"] == connection["id"]
    resources.set_binding(repository.repository_id, requirement_id, None)
    assert resources.get_binding(repository.repository_id, requirement_id) is None

    assert client.put(
        f"/agent-shell/api/model-requirements/{requirement_id}/binding",
        json={"connection_id": None, "unexpected": True},
    ).status_code == 422


def test_model_connection_api_uses_distinct_error_semantics(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    blocks = BlockStore(repository)
    resources = ModelResourceStore(tmp_path)
    app = FastAPI()
    app.include_router(build_model_connection_router(repository, blocks, resources))
    client = TestClient(app)

    created = client.post(
        "/agent-shell/api/model-connections",
        json=connection_payload(),
    )
    assert created.status_code == 200

    cases = [
        (
            client.post("/agent-shell/api/model-connections", json=connection_payload()),
            409,
            "model_connection_name_conflict",
            "errors.modelConnectionNameConflict",
        ),
        (
            client.post("/agent-shell/api/model-connections", json={"name": "Incomplete"}),
            422,
            "model_connection_invalid",
            "errors.modelConnectionInvalid",
        ),
        (
            client.get(
                "/agent-shell/api/model-connections/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            ),
            404,
            "model_connection_not_found",
            "errors.modelConnectionNotFound",
        ),
        (
            client.put(
                "/agent-shell/api/model-requirements/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/binding",
                json={"connection_id": None},
            ),
            404,
            "model_requirement_not_found",
            "errors.modelRequirementNotFound",
        ),
    ]
    for response, status, code, message_key in cases:
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
        assert response.json()["detail"]["message_key"] == message_key


def test_model_connection_rejects_blank_or_unknown_name_fields(tmp_path: Path) -> None:
    resources = ModelResourceStore(tmp_path)

    with pytest.raises(ValueError):
        resources.save_connection(
            "77777777-7777-4777-8777-777777777777",
            {**connection_payload("   ")},
        )
    with pytest.raises(ValueError):
        resources.save_connection(
            "88888888-8888-4888-8888-888888888888",
            {**connection_payload(), "unexpected": True},
        )


def test_model_requirement_binding_resolves_into_runtime_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    requirement_id = repository.new_configuration_id()
    connection = resources.save_connection(
        "66666666-6666-4666-8666-666666666666",
        connection_payload(),
    )
    resources.set_binding(repository.repository_id, requirement_id, connection["id"])
    captured: dict[str, object] = {}
    model = object()

    monkeypatch.setattr(
        agent_builder_module,
        "_build_chat_model",
        lambda block, credential, _clients: captured.update(
            block=block, credential=credential
        ) or model,
    )
    monkeypatch.setattr(
        agent_builder_module,
        "build_deepagents_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(
            backend=None,
            middleware=(),
            initial_files={},
            skill_sources=(),
            permissions=(),
            workspace=SimpleNamespace(initial_files={}),
        ),
    )
    builder = runtime_builder(tmp_path, repository, resources)
    profile = builder._materialize_profile(
        {
            "model-requirement": requirement_id,
            "filesystem": "filesystem-id",
            "filesystem-tools": "filesystem-tools-id",
        },
        {
            "model-requirement": {"id": requirement_id, "name": "Reasoning", "description": "Use reasoning."},
            "filesystem": {"id": "filesystem-id", "name": "Workspace"},
            "filesystem-tools": {"id": "filesystem-tools-id", "name": "Workspace tools"},
        },
        filesystem_mode="composite",
        scope="main_agent",
        owner_id="main-agent-id",
        owner_name="Main Agent",
    )

    assert profile.model is model
    assert captured["credential"] == "do-not-export-this-secret"
    assert captured["block"]["provider"] == "openai"


def test_runtime_reports_structured_unbound_requirement_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    requirement_id = repository.new_configuration_id()
    monkeypatch.setattr(
        agent_builder_module,
        "build_deepagents_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(
            backend=None, middleware=(), initial_files={}, skill_sources=(), permissions=(), workspace=SimpleNamespace(initial_files={})
        ),
    )
    builder = runtime_builder(tmp_path, repository, resources)

    with pytest.raises(AgentRuntimeError) as raised:
        builder._materialize_profile(
            {"model-requirement": requirement_id},
            {"model-requirement": {"id": requirement_id, "name": "Reasoning", "description": "Use reasoning."}},
            filesystem_mode="composite",
            scope="main_agent",
            owner_id="main-agent-id",
            owner_name="Main Agent",
        )
    assert raised.value.code == "model_requirement_unbound"
    assert raised.value.status_code == 409
    assert raised.value.validation_report is not None
    assert raised.value.validation_report.issues[0].path == "capability_refs.model-requirement"
    assert raised.value.validation_report.issues[0].message_key == (
        "validation.issue.modelRequirementUnbound"
    )


def test_runtime_reports_structured_error_when_requirement_reference_is_missing(
    tmp_path: Path,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    requirement_id = repository.new_configuration_id()
    builder = runtime_builder(tmp_path, repository, resources)

    with pytest.raises(AgentRuntimeError) as raised:
        builder._materialize_profile(
            {},
            {
                "model-requirement": {
                    "id": requirement_id,
                    "name": "Reasoning",
                    "description": "Use reasoning.",
                }
            },
            filesystem_mode="composite",
            scope="main_agent",
            owner_id="main-agent-id",
            owner_name="Main Agent",
        )

    assert raised.value.code == "model_requirement_unbound"
    assert raised.value.status_code == 409
    assert raised.value.validation_report is not None
    assert raised.value.validation_report.issues[0].message_key == (
        "validation.issue.modelRequirementUnbound"
    )


def test_runtime_reports_structured_error_for_missing_bound_connection(
    tmp_path: Path,
) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    requirement_id = repository.new_configuration_id()
    missing_connection_id = "abababab-abab-4aba-8aba-abababababab"
    stale_snapshot = ModelResourceSnapshot.capture(
        [],
        EnvironmentSnapshot.capture({}),
        {
            repository.repository_id: {
                requirement_id: missing_connection_id,
            }
        },
    )
    builder = runtime_builder(
        tmp_path,
        repository,
        resources,
        model_resources=stale_snapshot,
    )

    with pytest.raises(AgentRuntimeError) as raised:
        builder._materialize_profile(
            {"model-requirement": requirement_id},
            {
                "model-requirement": {
                    "id": requirement_id,
                    "name": "Reasoning",
                    "description": "Use reasoning.",
                }
            },
            filesystem_mode="composite",
            scope="main_agent",
            owner_id="main-agent-id",
            owner_name="Main Agent",
        )

    assert raised.value.code == "model_requirement_unbound"
    assert raised.value.status_code == 409
    assert raised.value.validation_report is not None
    assert raised.value.validation_report.issues[0].message_key == (
        "validation.issue.modelRequirementUnbound"
    )


def test_request_resource_clones_freeze_connection_and_binding_views(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    resources = ModelResourceStore(tmp_path)
    connection_id = "77777777-7777-4777-8777-777777777777"
    requirement_id = repository.new_configuration_id()
    resources.save_connection(connection_id, connection_payload())
    resources.set_binding(repository.repository_id, requirement_id, connection_id)
    snapshot = resources.snapshot()

    resources.save_connection(connection_id, {**connection_payload("Changed"), "model": "new-model", "credential": "new-secret"})
    resources.set_binding(repository.repository_id, requirement_id, None)

    assert snapshot.resolve_connection(connection_id)["model"] == "gpt-local"
    assert snapshot.resolve_connection(connection_id)["credential"] == "do-not-export-this-secret"
    assert snapshot.get_binding(repository.repository_id, requirement_id) == connection_id
    assert not hasattr(snapshot, "save_connection")


def test_bundle_exports_requirement_without_model_connection_fields(tmp_path: Path) -> None:
    repository = FileConfigRepository.empty(tmp_path)
    blocks = BlockStore(repository)
    requirement_id = repository.new_configuration_id()
    blocks.save_block(
        "model-requirement",
        requirement_id,
        {"name": "Portable requirement", "description": "Use a local mapped model."},
    )
    ModelResourceStore(tmp_path).save_connection(
        "33333333-3333-4333-8333-333333333333",
        connection_payload(),
    )
    runtime_root = tmp_path / "runtime"
    exported = ConfigurationBundleExporter(
        repository,
        packages_dir=tmp_path / "packages",
        skills_dir=tmp_path / "skills",
        runtime_root=runtime_root,
    ).export(
        BundleRoot(kind="component", source_id=requirement_id, type="model-requirement")
    )
    assert b"do-not-export-this-secret" not in exported.content
    assert b"api.example.com" not in exported.content
    parsed = parse_bundle(exported.content)
    assert parsed.manifest.records[0].component_type == "model-requirement"
    assert set(parsed.manifest.records[0].payload) == {"description"}

    preview = BundleImportPlanner(
        repository,
        packages_dir=tmp_path / "packages",
        skills_dir=tmp_path / "skills",
        runtime_root=runtime_root,
    ).preview(exported.content)
    assert preview.target_ids[requirement_id] != requirement_id
    assert any(issue["code"] == "model_requirement_unbound" for issue in preview.public_plan["warnings"])
