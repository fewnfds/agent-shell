from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent_shell.storage import atomic_files
from agent_shell.storage import file_config
from agent_shell.storage.file_config import FileConfigRepository


MAIN_AGENT_ID = "11111111-1111-4111-8111-111111111111"
REQUIREMENT_ID = "22222222-2222-4222-8222-222222222222"
WORKFLOW_ID = "33333333-3333-4333-8333-333333333333"


def test_unrelated_config_mutation_does_not_replace_unchanged_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FileConfigRepository(tmp_path / "data")
    repository.update_config(
        lambda config: config["main_agents"].append(
            {"id": MAIN_AGENT_ID, "name": "Existing Agent"}
        )
    )
    main_agent_path = (
        repository.config_root
        / "agents"
        / "main"
        / f"{MAIN_AGENT_ID}.yaml"
    )
    unchanged_mtime_ns = 1_700_000_000_000_000_000
    os.utime(
        main_agent_path,
        ns=(unchanged_mtime_ns, unchanged_mtime_ns),
    )
    original_replace = atomic_files.os.replace

    def deny_main_agent_replace(source: Path, destination: Path) -> None:
        if Path(destination) == main_agent_path:
            raise PermissionError(5, "injected Windows sharing denial")
        original_replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", deny_main_agent_replace)

    repository.update_config(
        lambda config: config["workflows"].append(
            {"id": WORKFLOW_ID, "name": "New Workflow"}
        )
    )

    assert main_agent_path.stat().st_mtime_ns == unchanged_mtime_ns
    assert (
        repository.config_root
        / "workflows"
        / f"{WORKFLOW_ID}.yaml"
    ).is_file()


def test_failed_config_write_keeps_live_and_persisted_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FileConfigRepository(tmp_path / "data")
    repository.update_config(
        lambda config: config["main_agents"].append(
            {"id": MAIN_AGENT_ID, "name": "Original"}
        )
    )
    original_write = file_config.write_text_atomic

    def fail_candidate(path: Path, text: str) -> None:
        if path.name == f"{MAIN_AGENT_ID}.yaml" and "Changed" in text:
            raise OSError("candidate write failed")
        original_write(path, text)

    monkeypatch.setattr(file_config, "write_text_atomic", fail_candidate)

    with pytest.raises(OSError, match="candidate write failed"):
        repository.update_config(
            lambda config: config["main_agents"][0].__setitem__(
                "name", "Changed"
            )
        )

    assert repository.config()["main_agents"][0]["name"] == "Original"
    assert FileConfigRepository(tmp_path / "data").config()["main_agents"][0][
        "name"
    ] == "Original"


def test_config_mutation_rejects_noncanonical_duplicate_and_casefold_identity(
    tmp_path: Path,
) -> None:
    repository = FileConfigRepository(tmp_path / "data")

    with pytest.raises(ValueError, match="canonical lowercase UUID4"):
        repository.update_config(
            lambda config: config["main_agents"].append(
                {"id": "not-a-uuid", "name": "Invalid"}
            )
        )

    def duplicate_id(config: dict) -> None:
        config["main_agents"].append(
            {"id": MAIN_AGENT_ID, "name": "Main"}
        )
        config["subagents"].append(
            {
                "id": MAIN_AGENT_ID,
                "component_name": "Worker",
                "name": "worker",
            }
        )

    with pytest.raises(ValueError, match="duplicated"):
        repository.update_config(duplicate_id)

    def duplicate_name(config: dict) -> None:
        config["components"]["model-requirement"] = [
            {"id": MAIN_AGENT_ID, "name": "Shared", "description": "One."},
            {"id": REQUIREMENT_ID, "name": "shared", "description": "Two."},
        ]

    with pytest.raises(ValueError, match="conflicts"):
        repository.update_config(duplicate_name)

    assert repository.config()["main_agents"] == []
    assert repository.config()["subagents"] == []
    assert repository.config()["components"] == {}


@pytest.mark.parametrize(
    ("filename_id", "changes", "message"),
    [
        (
            MAIN_AGENT_ID,
            {"kind": "subagent"},
            "kind",
        ),
        (
            MAIN_AGENT_ID,
            {"schema_version": 3},
            "schema_version",
        ),
        (
            MAIN_AGENT_ID,
            {"type": "filesystem"},
            "type",
        ),
        (
            REQUIREMENT_ID,
            {"id": MAIN_AGENT_ID},
            "filename",
        ),
    ],
)
def test_config_load_rejects_mismatched_document_envelope(
    tmp_path: Path,
    filename_id: str,
    changes: dict[str, object],
    message: str,
) -> None:
    repository = FileConfigRepository(tmp_path / "data")
    path = (
        repository.config_root
        / "components"
        / "model-requirement"
        / f"{filename_id}.yaml"
    )
    path.parent.mkdir(parents=True)
    document = {
        "kind": "component",
        "type": "model-requirement",
        "schema_version": 2,
        "id": filename_id,
        "name": "Requirement",
        "payload": {"description": "Reasoning-capable model."},
        **changes,
    }
    path.write_text(
        yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        FileConfigRepository(tmp_path / "data")
