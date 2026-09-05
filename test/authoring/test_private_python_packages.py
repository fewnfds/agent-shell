from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

from agent_shell.command_packages import CommandPackageRuntime, scan_command_package
from agent_shell.python_packages.authoring import PythonPackageAuthoringService
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository

from .app_support import make_client


def _write_router_template(data_root: Path, *, key: str = "basic_router") -> Path:
    folder = data_root / "templates" / "workflow" / "command" / key
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.py").write_text(
        "def create_command():\n"
        "    branch = 'finish'\n"
        "    async def route(state, runtime):\n"
        "        return {'activate': [branch], 'update': {}}\n"
        "    return route\n",
        encoding="utf-8",
    )
    (folder / "requirements.txt").write_text("", encoding="utf-8")
    (folder / "helpers").mkdir()
    (folder / "helpers" / "rules.py").write_text("VALUE = 1\n", encoding="utf-8")
    return folder


def _create_command(client: TestClient, *, name: str = "Private router") -> dict:
    catalog_response = client.get("/agent-shell/api/python-package-templates/command")
    assert catalog_response.status_code == 200, catalog_response.text
    selected = catalog_response.json()["catalog"][0]
    response = client.post(
        "/agent-shell/api/blocks/command",
        json={
            "name": name,
            "python_package": {"folder": ""},
            "python_package_template": {
                "key": selected["key"],
                "revision": selected["revision"],
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _private_folder(data_root: Path, created: dict) -> Path:
    return (
        FileConfigRepository(data_root).python_packages_root
        / "command"
        / created["name"]
    )


def test_repository_examples_are_separate_template_catalog_entries(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    service = PythonPackageAuthoringService(
        templates_root=tmp_path / "templates",
        examples_root=repository / "examples",
        instances_root=tmp_path / "instances",
        runtime_root=tmp_path / "runtime",
    )

    middleware = service.template_catalog("custom-middleware")
    tools = service.template_catalog("custom-tool")

    assert middleware["errors"] == {}
    assert middleware["catalog"][0]["key"] == "内置示例-agent-additional-prompt"
    assert {file["path"] for file in middleware["catalog"][0]["files"]} == {
        "main.py",
        "requirements.txt",
    }
    assert tools["errors"] == {}
    assert tools["catalog"][0]["key"] == "内置示例-default"


def test_template_create_persists_identity_only_and_projects_recursive_paths(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    template = _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client)
        package = client.get(
            f"/agent-shell/api/blocks/command/{created['id']}/python-package"
        )

    assert created["python_package"] == {"folder": created["name"]}
    private_folder = _private_folder(data_root, created)
    assert (private_folder / "main.py").read_text(encoding="utf-8") == (
        template / "main.py"
    ).read_text(encoding="utf-8")
    manifest = json.loads((private_folder / "package.json").read_text(encoding="utf-8"))
    assert manifest == {
        "format_version": 1,
        "family": "workflow-node",
        "adapter": "command",
        "id": created["id"],
    }
    stored = yaml.safe_load(
        (
            FileConfigRepository(data_root).config_root
            / "components"
            / "command"
            / f"{created['id']}.yaml"
        ).read_text(encoding="utf-8")
    )
    assert stored["payload"] == {
        "python_package": {"folder": created["name"]},
        "mcp_refs": [],
    }
    assert package.status_code == 200, package.text
    projection = package.json()
    assert projection["owner_id"] == created["id"]
    assert [item["path"] for item in projection["files"]] == [
        "helpers/rules.py",
        "main.py",
        "package.json",
        "requirements.txt",
    ]
    prefix = (
        f"data/config_repos/Default/python_packages/command/{created['name']}/"
    )
    assert all(
        item["file_manager_path"] == f"{prefix}{item['path']}"
        for item in projection["files"]
    )
    assert all("content" not in item for item in projection["files"])


def test_private_package_files_use_file_manager_revision_and_refresh_projection(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client)
        projection = client.get(
            f"/agent-shell/api/blocks/command/{created['id']}/python-package"
        ).json()
        helper = next(item for item in projection["files"] if item["path"] == "helpers/rules.py")
        opened = client.get(
            "/agent-shell/api/file-manager/text", params={"path": helper["file_manager_path"]}
        ).json()
        private_file = _private_folder(data_root, created) / "helpers" / "rules.py"
        private_file.write_text("VALUE = 2\n", encoding="utf-8")
        conflict = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": helper["file_manager_path"],
                "content": "VALUE = 3\n",
                "revision": opened["revision"],
            },
        )
        latest = client.get(
            "/agent-shell/api/file-manager/text", params={"path": helper["file_manager_path"]}
        ).json()
        saved = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": helper["file_manager_path"],
                "content": "VALUE = 3\n",
                "revision": latest["revision"],
            },
        )
        refreshed = client.get(
            f"/agent-shell/api/blocks/command/{created['id']}/python-package"
        ).json()

    assert conflict.status_code == 409
    assert private_file.read_text(encoding="utf-8") == "VALUE = 3\n"
    assert saved.status_code == 200
    assert refreshed["revision"] != projection["revision"]


def test_manual_manifest_damage_is_reported_without_repair(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client)
        projection = client.get(
            f"/agent-shell/api/blocks/command/{created['id']}/python-package"
        ).json()
        manifest_file = next(
            item for item in projection["files"] if item["path"] == "package.json"
        )
        opened = client.get(
            "/agent-shell/api/file-manager/text", params={"path": manifest_file["file_manager_path"]}
        ).json()
        manifest = json.loads(opened["content"])
        manifest["id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        saved = client.put(
            "/agent-shell/api/file-manager/text",
            json={
                "path": manifest_file["file_manager_path"],
                "content": json.dumps(manifest),
                "revision": opened["revision"],
            },
        )
        inspected = client.get(
            f"/agent-shell/api/blocks/command/{created['id']}/python-package"
        )

    assert saved.status_code == 200
    assert inspected.status_code == 200
    assert inspected.json()["python_package_manifest"] is None
    assert inspected.json()["python_package_error"]["message_key"] == (
        "resource.error.pythonPackage.idMismatch"
    )


def test_loading_package_does_not_change_source_revision(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client, name="Stable revision router")

    packages_dir = FileConfigRepository(data_root).python_packages_root
    package_dir = packages_dir / "command" / created["name"]
    before = scan_command_package(package_dir, owner_id=created["id"])["revision"]
    runtime = CommandPackageRuntime(
        request_id="revision-test",
        packages_dir=packages_dir,
        runtime_root=tmp_path / "runtime",
    )
    runtime.command_for(created["id"], created["id"], created["python_package"])

    assert list(package_dir.rglob("*.pyc"))
    assert scan_command_package(package_dir, owner_id=created["id"])["revision"] == before
    asyncio.run(runtime.close())


def test_copy_and_delete_follow_complete_private_package_ownership(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client, name="Source router")
        copied_response = client.post(
            f"/agent-shell/api/blocks/command/{created['id']}/copy",
            json={"name": "Copied router"},
        )
        assert copied_response.status_code == 200, copied_response.text
        copied = copied_response.json()
        copied_folder = _private_folder(data_root, copied)
        original_manifest = json.loads(
            (copied_folder / "package.json").read_text(encoding="utf-8")
        )
        deleted = client.delete(f"/agent-shell/api/blocks/command/{copied['id']}")

    assert copied["python_package"] == {"folder": copied["name"]}
    assert original_manifest["id"] == copied["id"]
    assert deleted.status_code == 200
    assert not copied_folder.exists()


def test_component_rename_moves_private_package_without_changing_uuid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        created = _create_command(client, name="Original router")
        original_folder = _private_folder(data_root, created)
        renamed_response = client.put(
            f"/agent-shell/api/blocks/command/{created['id']}",
            json={
                "name": "路由 Français",
                "python_package": created["python_package"],
            },
        )

    assert renamed_response.status_code == 200, renamed_response.text
    renamed = renamed_response.json()
    renamed_folder = _private_folder(data_root, renamed)
    assert renamed["id"] == created["id"]
    assert renamed["python_package"] == {"folder": renamed["name"]}
    assert not original_folder.exists()
    assert renamed_folder.is_dir()
    assert json.loads(
        (renamed_folder / "package.json").read_text(encoding="utf-8")
    )["id"] == created["id"]

    with make_client(tmp_path, monkeypatch) as client:
        case_changed_response = client.put(
            f"/agent-shell/api/blocks/command/{created['id']}",
            json={
                "name": "路由 FRANÇAIS",
                "python_package": renamed["python_package"],
            },
        )

    assert case_changed_response.status_code == 200, case_changed_response.text
    case_changed = case_changed_response.json()
    assert case_changed["id"] == created["id"]
    assert case_changed["python_package"] == {"folder": "路由 FRANÇAIS"}
    assert "路由 FRANÇAIS" in {
        child.name for child in renamed_folder.parent.iterdir()
    }
    assert "路由 Français" not in {
        child.name for child in renamed_folder.parent.iterdir()
    }


def test_component_record_create_failure_rolls_back_new_private_package(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        selected = client.get("/agent-shell/api/python-package-templates/command").json()[
            "catalog"
        ][0]
        package_root = FileConfigRepository(
            data_root
        ).python_packages_root / "command"
        before = set(package_root.iterdir())

        def fail_save(*args, **kwargs) -> None:
            raise RuntimeError("record write failed")

        with monkeypatch.context() as failure_patch:
            failure_patch.setattr(BlockStore, "save_block", fail_save)
            with pytest.raises(RuntimeError, match="record write failed"):
                client.post(
                    "/agent-shell/api/blocks/command",
                    json={
                        "name": "Uncommitted router",
                        "python_package": {"folder": ""},
                        "python_package_template": {
                            "key": selected["key"],
                            "revision": selected["revision"],
                        },
                    },
                )

        assert set(package_root.iterdir()) == before
        assert client.get("/agent-shell/api/blocks/command").json() == []


def test_component_record_delete_failure_restores_only_its_private_package(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    _write_router_template(data_root)
    with make_client(tmp_path, monkeypatch) as client:
        target = _create_command(client, name="Rollback target")
        neighbor = _create_command(client, name="Stable neighbor")
        target_folder = _private_folder(data_root, target)
        neighbor_folder = _private_folder(data_root, neighbor)

        def fail_delete(*args, **kwargs) -> bool:
            raise RuntimeError("record delete failed")

        with monkeypatch.context() as failure_patch:
            failure_patch.setattr(BlockStore, "delete_block", fail_delete)
            with pytest.raises(RuntimeError, match="record delete failed"):
                client.delete(f"/agent-shell/api/blocks/command/{target['id']}")

        assert target_folder.is_dir()
        assert neighbor_folder.is_dir()
        assert client.get(f"/agent-shell/api/blocks/command/{target['id']}").status_code == 200
