from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from langgraph.store.base import BaseStore

from agent_shell.contracts import FilesystemBlock
from agent_shell.storage.owned_paths import resolve_data_root_relative_path


LIFECYCLE_NAMESPACE_ROOT = "workflow-lifecycle"
LIFECYCLE_INPUT_KEY = "request"
LIFECYCLE_FILESYSTEM_RECORD_VERSION = 1


def lifecycle_input_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "input")


def lifecycle_invocations_namespace(
    lifecycle_id: str,
    run_id: str,
) -> tuple[str, str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    if not run_id:
        raise ValueError("run_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "invocations", run_id)


def lifecycle_filesystem_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, "filesystem")


class WorkflowDataService:
    """Own Agent Shell records stored in the Server-injected LangGraph Store."""

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve()
        self._filesystem_lock = asyncio.Lock()

    def _configured_mapping_root(self, local_path: str, path_origin: str) -> Path:
        configured = Path(local_path)
        if path_origin == "absolute":
            if not configured.is_absolute():
                raise ValueError("absolute mapped local_path must be absolute")
            return configured.resolve()
        return resolve_data_root_relative_path(
            self._data_root,
            local_path,
            label="data-root-relative mapped local_path",
        )

    async def resolve_mapped_directories(
        self,
        store: BaseStore,
        lifecycle_id: str,
        filesystem_id: str,
        filesystem: FilesystemBlock,
    ) -> dict[str, Path]:
        if not filesystem_id:
            raise ValueError("filesystem_id must not be empty")
        namespace = lifecycle_filesystem_namespace(lifecycle_id)
        async with self._filesystem_lock:
            stored = await store.aget(namespace, filesystem_id)
            if stored is not None:
                mappings = stored.value.get("mappings")
                if not isinstance(mappings, list):
                    raise RuntimeError("the Workflow Lifecycle filesystem record is invalid")
                resolved: dict[str, Path] = {}
                for item in mappings:
                    if not isinstance(item, dict):
                        raise RuntimeError(
                            "the Workflow Lifecycle filesystem record is invalid"
                        )
                    virtual_path = item.get("virtual_path")
                    local_path = item.get("resolved_local_path")
                    if not isinstance(virtual_path, str) or not isinstance(local_path, str):
                        raise RuntimeError(
                            "the Workflow Lifecycle filesystem record is invalid"
                        )
                    target = Path(local_path)
                    if item.get("lifecycle_mode") == "dynamic":
                        target.mkdir(exist_ok=True)
                    if not target.is_dir():
                        raise RuntimeError(
                            "a resolved Workflow Lifecycle mapped directory is unavailable"
                        )
                    resolved[virtual_path] = target
                return resolved

            configured_mappings = (
                [
                    (
                        mapping.virtual_path,
                        mapping.local_path,
                        mapping.path_origin,
                        mapping.lifecycle_mode,
                    )
                    for mapping in filesystem.mapped_directories
                ]
                if filesystem.backend_type == "composite"
                else [
                    (
                        "/",
                        filesystem.workspace.local_path,
                        filesystem.workspace.path_origin,
                        "fixed",
                    )
                ]
            )
            records: list[dict[str, str]] = []
            resolved: dict[str, Path] = {}
            resolved_targets: set[str] = set()
            for virtual_path, local_path, path_origin, lifecycle_mode in configured_mappings:
                root = self._configured_mapping_root(local_path, path_origin)
                if not root.is_dir():
                    raise ValueError(
                        "configured filesystem root must be an existing directory: "
                        f"{local_path}"
                    )
                target = (
                    root / f"lifecycle-{lifecycle_id}"
                    if lifecycle_mode == "dynamic"
                    else root
                )
                canonical_target = target.resolve()
                canonical = str(canonical_target).casefold()
                if canonical in resolved_targets:
                    raise ValueError("resolved mapped local directories must be unique")
                resolved_targets.add(canonical)
                resolved[virtual_path] = canonical_target
                records.append(
                    {
                        "virtual_path": virtual_path,
                        "resolved_local_path": str(canonical_target),
                        "configured_root": str(root),
                        "path_origin": path_origin,
                        "lifecycle_mode": lifecycle_mode,
                    }
                )
                if lifecycle_mode == "dynamic":
                    canonical_target.mkdir(exist_ok=True)
            await store.aput(
                namespace,
                filesystem_id,
                {
                    "version": LIFECYCLE_FILESYSTEM_RECORD_VERSION,
                    "filesystem_id": filesystem_id,
                    "mappings": records,
                    "created_at": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                },
                index=False,
            )
            return resolved


__all__ = [
    "LIFECYCLE_INPUT_KEY",
    "LIFECYCLE_NAMESPACE_ROOT",
    "WorkflowDataService",
    "lifecycle_filesystem_namespace",
    "lifecycle_input_namespace",
    "lifecycle_invocations_namespace",
]
