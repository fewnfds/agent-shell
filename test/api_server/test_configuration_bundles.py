from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from agent_shell.configuration.bundles import transactions as bundle_transactions
from agent_shell.configuration.bundles.journal import (
    ImportJournal,
    JournalPackage,
    JournalRecord,
    JournalSkillPackage,
    claim_import_asset,
    recover_configuration_imports,
    transaction_root,
    write_import_journal,
)
from agent_shell.configuration.bundles.errors import BundleImportError
from agent_shell.configuration.bundles.planning import BundleImportPlanner
from agent_shell.configuration.bundles.transactions import commit_prepared_import
from agent_shell.storage.file_config import FileConfigRepository
from .support import create_main_agent, create_workflow, make_client, save_linear_workflow_graph


def _export_workflow_bundle(source_root: Path, monkeypatch: pytest.MonkeyPatch):
    source_root.mkdir()
    mapped = source_root / "shared-workspace"
    mapped.mkdir()
    with make_client(source_root, monkeypatch) as source:
        filesystem_response = source.post(
            "/api/blocks/filesystem",
            json={
                "name": "Portable workspace",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": str(mapped.resolve()),
                        "path_origin": "absolute",
                    }
                ],
            },
        )
        assert filesystem_response.status_code == 200, filesystem_response.text
        main_agent = create_main_agent(
            source,
            filesystem_id=filesystem_response.json()["id"],
        )
        subagent = source.post(
            "/api/subagents",
            json={
                "component_name": "Portable Worker",
                "name": "portable_worker",
                "description": "Handles portable delegated work.",
                "settings": {},
            },
        )
        assert subagent.status_code == 200, subagent.text
        requirement_id = next(
            reference["block_id"]
            for reference in main_agent["capability_refs"]
            if reference["type"] == "model-requirement"
        )
        for root in (
            {"kind": "component", "type": "model-requirement", "source_id": requirement_id},
            {"kind": "subagent", "source_id": subagent.json()["id"]},
            {"kind": "main_agent", "source_id": main_agent["id"]},
        ):
            root_export = source.post(
                "/api/configuration-bundles/export",
                json=root,
            )
            assert root_export.status_code == 200, root_export.text
        workflow = create_workflow(source, name="Portable Workflow")
        save_linear_workflow_graph(source, workflow, main_agent)
        exported = source.post(
            "/api/configuration-bundles/export",
            json={"kind": "workflow", "source_id": workflow["id"]},
        )
        assert exported.status_code == 200, exported.text
        source_config = FileConfigRepository(source_root / "data").config()
    return exported.content, workflow, source_config


def test_workflow_bundle_import_remaps_identity_and_requires_path_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workflow, source_config = _export_workflow_bundle(
        tmp_path / "source",
        monkeypatch,
    )
    with ZipFile(BytesIO(bundle)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    model_record = next(
        record
        for record in manifest["records"]
        if record.get("type") == "model-requirement"
    )
    assert set(model_record["payload"]) == {"description"}
    assert model_record["name"] == "Published model requirement"
    assert {asset["kind"] for asset in manifest["assets"]} == {"python-package"}

    target_root = tmp_path / "target"
    target_root.mkdir()
    target_workspace = target_root / "workspace"
    target_workspace.mkdir()
    with make_client(target_root, monkeypatch) as target:
        preview_response = target.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("portable.zip", bundle, "application/zip")},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["ready"] is False
        assert {issue["code"] for issue in preview["errors"]} == {
            "filesystem_binding_required"
        }
        binding = preview["filesystem_bindings"][0]
        assert binding["source_value"].endswith("shared-workspace")
        warning_codes = {warning["code"] for warning in preview["warnings"]}
        assert {
            "model_requirement_unbound",
            "trusted_python_package",
            "opaque_python_runtime_target",
            "workflow_imported_disabled",
        }.issubset(warning_codes)
        assert len(preview["plan_token"]) == 64

        invalid_rebind = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {
                "target_ids": preview["target_ids"],
                "filesystem_bindings": {
                    binding["binding_id"]: {
                        "value": "C:relative",
                        "path_origin": "data-root-relative",
                    }
                },
            },
        }
        rejected_rebind = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("portable.zip", bundle, "application/zip")},
            data={"request": json.dumps(invalid_rebind)},
        )
        assert rejected_rebind.status_code == 409, rejected_rebind.text

        request = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {
                "target_ids": preview["target_ids"],
                "filesystem_bindings": {
                    binding["binding_id"]: {
                        "value": str(target_workspace.resolve()),
                        "path_origin": "absolute",
                    }
                },
            },
        }
        imported_response = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("portable.zip", bundle, "application/zip")},
            data={"request": json.dumps(request)},
        )
        assert imported_response.status_code == 200, imported_response.text
        imported = imported_response.json()
        target_config = FileConfigRepository(target_root / "data").config()

    source_ids = set(preview["target_ids"])
    target_ids = set(preview["target_ids"].values())
    assert source_ids.isdisjoint(target_ids)
    assert imported["root"]["target_id"] == preview["target_ids"][workflow["id"]]
    imported_workflow = next(
        item
        for item in target_config["workflows"]
        if item["id"] == imported["root"]["target_id"]
    )
    assert imported_workflow["enabled"] is False
    imported_main_id = next(
        node["config"]["main_agent_id"]
        for node in imported_workflow["definition"]["nodes"]
        if node["type"] == "agent"
    )
    assert imported_main_id in target_ids
    imported_main = next(
        item for item in target_config["main_agents"] if item["id"] == imported_main_id
    )
    assert all(
        reference["block_id"] in target_ids
        for reference in imported_main["capability_refs"]
    )
    imported_requirement = target_config["components"]["model-requirement"][0]
    assert set(imported_requirement) == {"id", "name", "description"}
    imported_filesystem = target_config["components"]["filesystem"][0]
    assert imported_filesystem["mapped_directories"][0]["local_path"] == str(
        target_workspace.resolve()
    )

    output = target_config["components"]["agent-event-output"][0]
    target_repository = FileConfigRepository(target_root / "data")
    package_folder = (
        target_repository.python_package_instances_root
        / "agent-event-output"
        / output["id"]
    )
    assert output["python_package"]["folder"] == output["id"]
    assert json.loads((package_folder / "package.json").read_text(encoding="utf-8"))[
        "id"
    ] == output["id"]
    assert not any(
        path.name.startswith(".agent-shell-import-owner-")
        for path in package_folder.iterdir()
    )
    assert len(source_config["workflows"]) == 1


def test_bundle_import_failure_removes_staged_configuration_and_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _workflow, _source_config = _export_workflow_bundle(
        tmp_path / "source-failure",
        monkeypatch,
    )
    target_root = tmp_path / "target-failure"
    target_root.mkdir()
    target_workspace = target_root / "workspace"
    target_workspace.mkdir()
    with make_client(target_root, monkeypatch) as target:
        preview = target.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("portable.zip", bundle, "application/zip")},
        ).json()
        binding = preview["filesystem_bindings"][0]
        request = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {
                "target_ids": preview["target_ids"],
                "filesystem_bindings": {
                    binding["binding_id"]: {
                        "value": str(target_workspace.resolve()),
                        "path_origin": "absolute",
                    }
                },
            },
        }
        original_update = FileConfigRepository.update_config

        def fail_import(self, mutator):
            def wrapped(config):
                result = mutator(config)
                ids = {
                    record.get("id")
                    for records in config.get("components", {}).values()
                    for record in records
                    if isinstance(record, dict)
                }
                if ids.intersection(preview["target_ids"].values()):
                    raise ValueError("injected import failure")
                return result

            return original_update(self, wrapped)

        monkeypatch.setattr(FileConfigRepository, "update_config", fail_import)
        response = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("portable.zip", bundle, "application/zip")},
            data={"request": json.dumps(request)},
        )
        assert response.status_code == 409, response.text

    target_ids = set(preview["target_ids"].values())
    target_repository = FileConfigRepository(target_root / "data")
    config_root = target_repository.config_root
    assert not any(path.stem in target_ids for path in config_root.rglob("*.yaml"))
    packages = config_root / "python_package_instances"
    assert not any(path.name in target_ids for path in packages.rglob("*"))
    journals = config_root / "configuration-imports" / "journals"
    assert not journals.exists() or not any(journals.iterdir())


def test_stale_target_uuid_is_rejected_without_deleting_current_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "stale-target-source"
    source_root.mkdir()
    with make_client(source_root, monkeypatch) as source:
        created = source.post(
            "/api/blocks/system-prompt",
            json={"name": "Portable prompt", "system_prompt": "Be precise."},
        )
        assert created.status_code == 200, created.text
        exported = source.post(
            "/api/configuration-bundles/export",
            json={
                "kind": "component",
                "type": "system-prompt",
                "source_id": created.json()["id"],
            },
        )
        assert exported.status_code == 200, exported.text

    target_root = tmp_path / "stale-target"
    data_root = target_root / "data"
    repository = FileConfigRepository(data_root)
    packages_dir = repository.python_package_instances_root
    skills_dir = repository.skill_package_instances_root
    runtime_root = target_root / "runtime"
    prepared = BundleImportPlanner(
        repository,
        packages_dir=packages_dir,
        skills_dir=skills_dir,
        runtime_root=runtime_root,
    ).preview(exported.content)
    target_id = next(iter(prepared.target_ids.values()))
    repository.update_config(
        lambda config: config["components"].setdefault(
            "system-prompt", []
        ).append(
            {
                "id": target_id,
                "name": "Current prompt",
                "system_prompt": "Keep this configuration.",
            }
        )
    )

    with pytest.raises(BundleImportError, match="target UUID state changed"):
        commit_prepared_import(
            repository,
            prepared,
            packages_dir=packages_dir,
            skills_dir=skills_dir,
            runtime_root=runtime_root,
        )

    current = repository.config()["components"]["system-prompt"]
    assert current == [
        {
            "id": target_id,
            "name": "Current prompt",
            "system_prompt": "Keep this configuration.",
        }
    ]
    assert (
        repository.config_root / "components" / "system-prompt" / f"{target_id}.yaml"
    ).is_file()
    journals = transaction_root(repository.config_root) / "journals"
    assert not journals.exists() or not any(journals.iterdir())


def test_committed_import_survives_deferred_housekeeping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "committed-source"
    source_root.mkdir()
    with make_client(source_root, monkeypatch) as source:
        created = source.post(
            "/api/blocks/system-prompt",
            json={"name": "Committed prompt", "system_prompt": "Be precise."},
        )
        assert created.status_code == 200, created.text
        exported = source.post(
            "/api/configuration-bundles/export",
            json={
                "kind": "component",
                "type": "system-prompt",
                "source_id": created.json()["id"],
            },
        )
        assert exported.status_code == 200, exported.text

    target_root = tmp_path / "committed-target"
    target_root.mkdir()
    original_cleanup = bundle_transactions.cleanup_import_journal

    def defer_committed_cleanup(data_root: Path, journal: ImportJournal) -> None:
        if journal.state == "committed":
            raise OSError("injected housekeeping failure")
        original_cleanup(data_root, journal)

    monkeypatch.setattr(
        bundle_transactions,
        "cleanup_import_journal",
        defer_committed_cleanup,
    )
    with make_client(target_root, monkeypatch) as target:
        preview = target.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
        ).json()
        response = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={
                "request": json.dumps(
                    {
                        "bundle_sha256": preview["bundle_sha256"],
                        "plan_token": preview["plan_token"],
                        "resolutions": {"target_ids": preview["target_ids"]},
                    }
                )
            },
        )
        assert response.status_code == 200, response.text
        target_id = next(iter(preview["target_ids"].values()))
        imported_ids = {
            item["id"]
            for item in target.get("/api/blocks/system-prompt").json()
        }
        assert imported_ids == {target_id}

    data_root = target_root / "data"
    repository_root = FileConfigRepository(data_root).config_root
    journal_files = list((transaction_root(repository_root) / "journals").glob("*.json"))
    assert len(journal_files) == 1
    assert json.loads(journal_files[0].read_text(encoding="utf-8"))["state"] == (
        "committed"
    )

    recover_configuration_imports(data_root)

    assert FileConfigRepository(data_root).config()["components"]["system-prompt"][
        0
    ]["id"] == target_id
    assert not journal_files[0].exists()


def test_skill_private_package_import_is_independent_from_target_templates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "skill-source"
    source_root.mkdir()
    source_skill = source_root / "data" / "skills-template" / "group" / "outline"
    source_skill.mkdir(parents=True)
    source_skill.joinpath("SKILL.md").write_text(
        "---\nname: outline\ndescription: Build an outline.\n---\n\nSource steps.\n",
        encoding="utf-8",
    )
    with make_client(source_root, monkeypatch) as source:
        created = source.post(
            "/api/blocks/skill",
            json={
                "name": "Outline Skill",
                "skill_template_paths": ["group/outline"],
            },
        )
        assert created.status_code == 200, created.text
        source_id = created.json()["id"]
        private_manifest = (
            FileConfigRepository(source_root / "data").skill_package_instances_root
            / source_id
            / "outline"
            / "SKILL.md"
        )
        private_manifest.write_text("user-authored invalid content\n", encoding="utf-8")
        exported = source.post(
            "/api/configuration-bundles/export",
            json={
                "kind": "component",
                "type": "skill",
                "source_id": source_id,
            },
        )
        assert exported.status_code == 200, exported.text

    target_root = tmp_path / "skill-target"
    target_root.mkdir()
    target_skill = target_root / "data" / "skills-template" / "other" / "outline"
    target_skill.mkdir(parents=True)
    target_skill.joinpath("SKILL.md").write_text(
        "---\nname: outline\ndescription: Different content.\n---\n\nTarget steps.\n",
        encoding="utf-8",
    )
    with make_client(target_root, monkeypatch) as target:
        preview_response = target.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("skill.zip", exported.content, "application/zip")},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["ready"] is True
        assert preview["errors"] == []
        assert preview["skill_packages"] == [
            {
                "source_id": source_id,
                "target_id": preview["target_ids"][source_id],
                "sha256": next(
                    asset["sha256"]
                    for asset in json.loads(
                        ZipFile(BytesIO(exported.content)).read("manifest.json")
                    )["assets"]
                    if asset["kind"] == "skill-package"
                ),
            }
        ]
        request = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {"target_ids": preview["target_ids"]},
        }
        imported = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("skill.zip", exported.content, "application/zip")},
            data={"request": json.dumps(request)},
        )
        assert imported.status_code == 200, imported.text

    target_id = preview["target_ids"][source_id]
    target_repository = FileConfigRepository(target_root / "data")
    imported_record = target_repository.config()["components"]["skill"][0]
    assert imported_record["id"] == target_id
    assert imported_record["skill_package"] == {"folder": target_id}
    assert (
        target_repository.skill_package_instances_root
        / target_id
        / "outline"
        / "SKILL.md"
    ).read_text(encoding="utf-8") == "user-authored invalid content\n"
    assert "Different content" in target_skill.joinpath("SKILL.md").read_text(
        encoding="utf-8"
    )


def test_prepared_import_journal_recovery_removes_only_declared_new_paths(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    repository = FileConfigRepository(data_root)
    repository_root = repository.config_root
    transaction_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    target_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    journal = ImportJournal(
        transaction_id=transaction_id,
        bundle_sha256="0" * 64,
        state="prepared",
        records=[
            JournalRecord(kind="component", type="custom-tool", target_id=target_id)
        ],
        packages=[JournalPackage(adapter="agent-tool", target_id=target_id)],
        skill_packages=[JournalSkillPackage(target_id=target_id)],
    )
    root = transaction_root(repository_root)
    journal_path = root / "journals" / f"{transaction_id}.json"
    configuration = (
        repository_root / "components" / "custom-tool" / f"{target_id}.yaml"
    )
    package = (
        repository_root
        / "python_package_instances"
        / "agent-tool"
        / target_id
    )
    skill = repository_root / "skill_package_instances" / target_id
    staging = root / "staging" / transaction_id
    unrelated = repository_root / "skill_package_instances" / "keep"
    for folder in (configuration.parent, package, skill, staging, unrelated):
        folder.mkdir(parents=True, exist_ok=True)
    configuration.write_text("incomplete", encoding="utf-8")
    claim_import_asset(package, transaction_id)
    claim_import_asset(skill, transaction_id)
    write_import_journal(journal_path, journal)

    recover_configuration_imports(data_root)

    assert not configuration.exists()
    assert not package.exists()
    assert not skill.exists()
    assert not staging.exists()
    assert not journal_path.exists()
    assert unrelated.is_dir()


def test_name_conflict_requires_confirmation_and_import_plan_cannot_be_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "name-source"
    source_root.mkdir()
    with make_client(source_root, monkeypatch) as source:
        created = source.post(
            "/api/blocks/system-prompt",
            json={"name": "Shared prompt", "system_prompt": "Be precise."},
        )
        assert created.status_code == 200, created.text
        source_id = created.json()["id"]
        exported = source.post(
            "/api/configuration-bundles/export",
            json={
                "kind": "component",
                "type": "system-prompt",
                "source_id": source_id,
            },
        )
        assert exported.status_code == 200, exported.text

    target_root = tmp_path / "name-target"
    target_root.mkdir()
    with make_client(target_root, monkeypatch) as target:
        existing = target.post(
            "/api/blocks/system-prompt",
            json={"name": " shared prompt ", "system_prompt": "Existing."},
        )
        assert existing.status_code == 200, existing.text
        preview_response = target.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["ready"] is False
        assert preview["errors"] == []
        record = preview["records"][0]
        assert record["suggested_name"] == "Shared prompt (imported)"
        assert record["requires_confirmation"] is True

        base_request = {
            "bundle_sha256": preview["bundle_sha256"],
            "plan_token": preview["plan_token"],
            "resolutions": {"target_ids": preview["target_ids"]},
        }
        unconfirmed = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={"request": json.dumps(base_request)},
        )
        assert unconfirmed.status_code == 409, unconfirmed.text
        assert unconfirmed.json()["detail"]["issues"][0]["code"] == (
            "configuration_name_confirmation_required"
        )

        confirmed_request = deepcopy_json(base_request)
        confirmed_request["resolutions"]["names"] = {
            source_id: record["suggested_name"]
        }
        wrong_plan = deepcopy_json(confirmed_request)
        wrong_plan["resolutions"]["target_ids"][source_id] = (
            "33333333-3333-4333-8333-333333333333"
        )
        rejected_plan = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={"request": json.dumps(wrong_plan)},
        )
        assert rejected_plan.status_code == 409, rejected_plan.text

        wrong_digest = deepcopy_json(confirmed_request)
        wrong_digest["bundle_sha256"] = "0" * 64
        rejected_digest = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={"request": json.dumps(wrong_digest)},
        )
        assert rejected_digest.status_code == 409, rejected_digest.text

        imported = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={"request": json.dumps(confirmed_request)},
        )
        assert imported.status_code == 200, imported.text
        replayed = target.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("prompt.zip", exported.content, "application/zip")},
            data={"request": json.dumps(confirmed_request)},
        )
        assert replayed.status_code == 409, replayed.text
        prompts = target.get("/api/blocks/system-prompt").json()

    assert {prompt["name"] for prompt in prompts} == {
        "shared prompt",
        "Shared prompt (imported)",
    }
    assert existing.json()["id"] != preview["target_ids"][source_id]


def test_malformed_bundle_is_422_for_preview_and_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = b"not-a-zip"
    with make_client(tmp_path, monkeypatch) as client:
        preview = client.post(
            "/api/configuration-bundles/preview",
            files={"bundle": ("broken.zip", malformed, "application/zip")},
        )
        imported = client.post(
            "/api/configuration-bundles/import",
            files={"bundle": ("broken.zip", malformed, "application/zip")},
            data={
                "request": json.dumps(
                    {
                        "bundle_sha256": "0" * 64,
                        "plan_token": "0" * 64,
                        "resolutions": {"target_ids": {}},
                    }
                )
            },
        )

    assert preview.status_code == 422, preview.text
    assert imported.status_code == 422, imported.text
    assert preview.json()["detail"]["code"] == "configuration_bundle_invalid"
    assert imported.json()["detail"]["code"] == "configuration_bundle_invalid"


@pytest.mark.parametrize("name", ["CON", "PRN.txt", "com1.JSON"])
def test_bundle_download_avoids_windows_reserved_basenames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/api/blocks/system-prompt",
            json={"name": name, "system_prompt": "Portable prompt."},
        )
        assert created.status_code == 200, created.text
        exported = client.post(
            "/api/configuration-bundles/export",
            json={
                "kind": "component",
                "type": "system-prompt",
                "source_id": created.json()["id"],
            },
        )

    assert exported.status_code == 200, exported.text
    disposition = exported.headers["content-disposition"]
    assert 'filename="configuration-' in disposition
    assert disposition.endswith('.agent-shell-config.zip"')


def deepcopy_json(value: dict) -> dict:
    return json.loads(json.dumps(value))
