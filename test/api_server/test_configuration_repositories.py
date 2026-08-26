from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZipFile

import yaml

from agent_shell.configuration.repositories import list_configuration_repositories
from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import (
    ActiveRepositoryChangedError,
    FileConfigRepository,
)
from agent_shell.storage.workflows import WorkflowStore

from .support import *


def test_repository_switch_is_atomic_for_new_requests_and_preserves_old_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        initial = client.get("/api/configuration-repositories").json()
        initial_id = initial["active_id"]
        old_workflow = create_workflow(client, name="First repository Workflow")
        frozen = client.app.state.agent_runtime.capture()

        created = client.post(
            "/api/configuration-repositories",
            json={"name": "Alternate"},
        )
        assert created.status_code == 200, created.text
        alternate_id = created.json()["id"]
        activated = client.post(
            f"/api/configuration-repositories/{alternate_id}/activate"
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["active"] is True
        assert activated.json()["restart_required"] is False
        assert client.get("/api/workflows").json() == []

        new_workflow = create_workflow(client, name="Alternate repository Workflow")
        current = client.app.state.agent_runtime.capture()
        assert frozen.workflow_by_name(old_workflow["name"])["id"] == old_workflow["id"]
        assert frozen.workflow_by_name(new_workflow["name"]) is None
        assert current.workflow_by_name(old_workflow["name"]) is None
        assert current.workflow_by_name(new_workflow["name"])["id"] == new_workflow["id"]

        switched_back = client.post(
            f"/api/configuration-repositories/{initial_id}/activate"
        )
        assert switched_back.status_code == 200, switched_back.text
        assert [item["id"] for item in client.get("/api/workflows").json()] == [
            old_workflow["id"]
        ]
        listed = client.get("/api/configuration-repositories").json()
        assert listed["active_id"] == initial_id
        assert {item["name"] for item in listed["repositories"]} == {
            "Default",
            "Alternate",
        }


def test_repository_names_are_unique_without_switching_on_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        initial_id = client.get("/api/configuration-repositories").json()["active_id"]
        first = client.post(
            "/api/configuration-repositories",
            json={"name": "Portable"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["active"] is False
        assert client.get("/api/configuration-repositories").json()["active_id"] == initial_id

        conflict = client.post(
            "/api/configuration-repositories",
            json={"name": " portable "},
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["detail"]["code"] == "configuration_repository_conflict"


def test_repository_copy_download_and_activate_preserve_dangling_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        source_repository = client.get(
            "/api/configuration-repositories"
        ).json()["repositories"][0]
        workflow = create_workflow(client, name="Repairable Workflow")
        checkpointer = client.post(
            "/api/blocks/checkpointer",
            json={"name": "Temporary checkpoints", "durability": "sync"},
        ).json()
        updated = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                **{
                    key: workflow[key]
                    for key in (
                        "name",
                        "workflow_role",
                        "description",
                        "workflow_event_output_id",
                        "cancel_on_upstream_termination",
                        "recursion_limit",
                        "execution_timeout_seconds",
                        "max_concurrency",
                    )
                },
                "checkpointer_id": checkpointer["id"],
            },
        )
        assert updated.status_code == 200, updated.text
        deleted = client.delete(
            f"/api/blocks/checkpointer/{checkpointer['id']}"
        )
        assert deleted.status_code == 200, deleted.text

        downloaded = client.get(
            f"/api/configuration-repositories/{source_repository['id']}/download"
        )
        assert downloaded.status_code == 200, downloaded.text
        with ZipFile(BytesIO(downloaded.content)) as archive:
            workflow_documents = [
                archive.read(name)
                for name in archive.namelist()
                if name.startswith("repository/workflows/")
            ]
        assert checkpointer["id"].encode() in b"".join(workflow_documents)

        copied = client.post(
            f"/api/configuration-repositories/{source_repository['id']}/copy",
            json={"name": "Repairable copy"},
        )
        assert copied.status_code == 200, copied.text
        activated = client.post(
            f"/api/configuration-repositories/{copied.json()['id']}/activate"
        )
        assert activated.status_code == 200, activated.text
        copied_workflow = client.get("/api/workflows").json()[0]
        assert copied_workflow["id"] != workflow["id"]
        assert copied_workflow["checkpointer_id"] == checkpointer["id"]
        issues = [
            issue
            for issue in activated.json()["validation"]["issues"]
            if issue["owner_id"] == copied_workflow["id"]
            and issue["code"] == "configuration.reference_not_found"
        ]
        assert len(issues) == 1
        assert issues[0]["path"] == "checkpointer_id"
        assert issues[0]["message_args"]["reference_id"] == checkpointer["id"]


def test_repository_copy_rewrites_ids_references_assets_and_model_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        source_repository = client.get(
            "/api/configuration-repositories"
        ).json()["repositories"][0]
        main_agent = create_main_agent(client)
        workflow = create_workflow(client, name="Copied repository Workflow")
        source_graph = save_linear_workflow_graph(client, workflow, main_agent)
        source_config = FileConfigRepository(tmp_path / "data").config()
        source_ids = FileConfigRepository._configuration_ids(source_config)
        source_requirement = next(
            item
            for item in source_config["components"]["model-requirement"]
        )
        source_output = next(
            item
            for item in source_config["components"]["agent-event-output"]
        )
        source_binding = next(
            item
            for item in client.get("/api/model-requirements").json()
            if item["id"] == source_requirement["id"]
        )

        copied_response = client.post(
            f"/api/configuration-repositories/{source_repository['id']}/copy",
            json={"name": "Independent copy"},
        )
        assert copied_response.status_code == 200, copied_response.text
        copied_repository = copied_response.json()
        assert copied_repository["active"] is False

        downloaded = client.get(
            f"/api/configuration-repositories/{copied_repository['id']}/download"
        )
        assert downloaded.status_code == 200, downloaded.text
        with ZipFile(BytesIO(downloaded.content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
            archive_bytes = b"".join(archive.read(name) for name in names)
        assert manifest["format"] == "agent-shell.configuration-repository"
        assert not any("model-connections" in name for name in names)
        assert b"provider-test-secret" not in archive_bytes

        activated = client.post(
            f"/api/configuration-repositories/{copied_repository['id']}/activate"
        )
        assert activated.status_code == 200, activated.text
        copied_config = FileConfigRepository(tmp_path / "data").config()
        copied_ids = FileConfigRepository._configuration_ids(copied_config)
        assert copied_ids
        assert copied_ids.isdisjoint(source_ids)
        assert len(copied_ids) == len(source_ids)

        copied_agent = client.get("/api/main-agents").json()[0]
        copied_workflow = client.get("/api/workflows").json()[0]
        copied_requirement = client.get(
            "/api/blocks/model-requirement"
        ).json()[0]
        copied_output = client.get("/api/blocks/agent-event-output").json()[0]
        assert copied_agent["id"] != main_agent["id"]
        assert {
            reference["block_id"]
            for reference in copied_agent["capability_refs"]
        }.issubset(copied_ids)
        assert copied_workflow["enabled"] is False
        copied_graph = client.get(
            f"/api/workflows/{copied_workflow['id']}/graph"
        ).json()
        assert copied_graph["layout"] == source_graph["layout"]
        copied_agent_node = next(
            node
            for node in copied_graph["definition"]["nodes"]
            if node["type"] == "agent"
        )
        assert copied_agent_node["config"]["main_agent_id"] == copied_agent["id"]
        copied_binding = next(
            item
            for item in client.get("/api/model-requirements").json()
            if item["id"] == copied_requirement["id"]
        )
        assert copied_binding["binding"] == source_binding["binding"]

        copied_package = (
            tmp_path
            / "data"
            / "configuration-repositories"
            / copied_repository["id"]
            / "python_package_instances"
            / "agent-event-output"
            / copied_output["id"]
        )
        assert copied_package.is_dir()
        assert json.loads(
            (copied_package / "package.json").read_text(encoding="utf-8")
        )["id"] == copied_output["id"]
        assert not (copied_package.parent / source_output["id"]).exists()

        active_delete = client.delete(
            f"/api/configuration-repositories/{copied_repository['id']}"
        )
        assert active_delete.status_code == 409
        assert active_delete.json()["detail"]["code"] == (
            "active_configuration_repository_delete_forbidden"
        )

        switched_back = client.post(
            f"/api/configuration-repositories/{source_repository['id']}/activate"
        )
        assert switched_back.status_code == 200, switched_back.text
        deleted = client.delete(
            f"/api/configuration-repositories/{copied_repository['id']}"
        )
        assert deleted.json() == {"ok": True}
        listed_ids = {
            item["id"]
            for item in client.get("/api/configuration-repositories").json()[
                "repositories"
            ]
        }
        assert copied_repository["id"] not in listed_ids
        bindings_path = tmp_path / "data" / "config" / "model-bindings.yaml"
        bindings = yaml.safe_load(bindings_path.read_text(encoding="utf-8"))
        assert copied_repository["id"] not in bindings


def test_invalid_repository_name_does_not_leave_an_orphan_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/configuration-repositories", json={"name": "   "})
        assert response.status_code == 409, response.text
        repository_root = tmp_path / "data" / "configuration-repositories"
        assert len(list(repository_root.iterdir())) == 1


def test_repository_listing_ignores_only_internal_work_directories(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    repository = FileConfigRepository(data_root)
    repository_root = data_root / "configuration-repositories"
    (repository_root / ".repository-copy-interrupted").mkdir()
    (repository_root / ".repository-delete-interrupted").mkdir()

    assert [
        item.id for item in list_configuration_repositories(data_root)
    ] == [repository.repository_id]

    (repository_root / "invalid-repository").mkdir()
    with pytest.raises(ValueError, match="repository manifest is invalid"):
        list_configuration_repositories(data_root)


def test_configuration_stores_reject_writes_after_repository_switch(
    tmp_path: Path,
) -> None:
    repository = FileConfigRepository(tmp_path / "data")
    expected_repository_id = repository.repository_id
    alternate_id = str(repository.create_repository("Alternate")["id"])
    repository.switch_repository(alternate_id)
    before = repository.config()

    mutations = (
        lambda: AgentConfigStore(repository).delete_item(
            "main_agents",
            "11111111-1111-4111-8111-111111111111",
            expected_repository_id=expected_repository_id,
        ),
        lambda: WorkflowStore(repository).delete_item(
            "11111111-1111-4111-8111-111111111111",
            expected_repository_id=expected_repository_id,
        ),
        lambda: BlockStore(repository).delete_block(
            "unsupported-test-type",
            "11111111-1111-4111-8111-111111111111",
            expected_repository_id=expected_repository_id,
        ),
    )

    for mutate in mutations:
        with pytest.raises(ActiveRepositoryChangedError):
            mutate()
        assert repository.config() == before

    with pytest.raises(ActiveRepositoryChangedError):
        with repository.exclusive_config_mutation(
            expected_repository_id=expected_repository_id
        ):
            raise AssertionError("the stale mutation body must not run")
