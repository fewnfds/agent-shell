from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langgraph.store.memory import InMemoryStore

from agent_shell.contracts import FilesystemBlock
from agent_shell.runtime.workflow_data import WorkflowDataService


def _filesystem(root: Path, *, lifecycle_mode: str) -> FilesystemBlock:
    return FilesystemBlock.model_validate(
        {
            "name": "Workflow filesystem",
            "mapped_directories": [
                {
                    "virtual_path": "/workspace/",
                    "local_path": str(root),
                    "path_origin": "absolute",
                    "lifecycle_mode": lifecycle_mode,
                }
            ],
        }
    )


def test_workflow_data_resolves_and_reuses_lifecycle_filesystem_mapping(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[Path, Path]:
        data_root = tmp_path / "data"
        mapping_root = tmp_path / "mapped"
        data_root.mkdir()
        mapping_root.mkdir()
        service = WorkflowDataService(data_root)
        store = InMemoryStore()
        first = await service.resolve_mapped_directories(
            store,
            "lifecycle-1",
            "filesystem-1",
            _filesystem(mapping_root, lifecycle_mode="dynamic"),
        )
        second = await service.resolve_mapped_directories(
            store,
            "lifecycle-1",
            "filesystem-1",
            _filesystem(mapping_root, lifecycle_mode="dynamic"),
        )
        return first["/workspace/"], second["/workspace/"]

    first, second = asyncio.run(scenario())
    assert first == second == (tmp_path / "mapped" / "lifecycle-lifecycle-1")
    assert first.is_dir()


def test_workflow_data_rejects_data_relative_mapping_escape(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    with pytest.raises(ValueError):
        FilesystemBlock.model_validate(
            {
                "name": "Workflow filesystem",
                "mapped_directories": [
                    {
                        "virtual_path": "/workspace/",
                        "local_path": "../outside",
                        "path_origin": "data-root-relative",
                        "lifecycle_mode": "fixed",
                    }
                ],
            }
        )
