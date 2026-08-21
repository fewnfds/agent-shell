from __future__ import annotations

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


def test_invalid_repository_name_does_not_leave_an_orphan_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/configuration-repositories", json={"name": "   "})
        assert response.status_code == 409, response.text
        repository_root = tmp_path / "data" / "configuration-repositories"
        assert len(list(repository_root.iterdir())) == 1


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
