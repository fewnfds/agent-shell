from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping

from agent_shell.capability_manifest import (
    FILESYSTEM_TOOL_NAMES,
    MINIMAL_FILESYSTEM_TOOL_NAMES,
)
from agent_shell.contracts import (
    FilesystemBlock,
    FilesystemPermissionsBlock,
    SkillBlock,
)
from agent_shell.storage.owned_paths import is_plain_tree
from agent_shell.validation.capability_assembly import FilesystemMode


class DeepAgentsCapabilityError(ValueError):
    """Raised when validated capability blocks cannot be materialized."""


@dataclass(frozen=True)
class DeepAgentsWorkspace:
    """Shared ordinary storage used to build consumer-specific backend views."""

    default_backend: Any
    routes: dict[str, Any]
    initial_files: dict[str, Any]


@dataclass(frozen=True)
class DeepAgentsCapabilities:
    backend: Any
    middleware: tuple[Any, ...]
    initial_files: dict[str, Any]
    selected_skills: tuple[str, ...]
    skill_sources: tuple[str, ...]
    permissions: tuple[Any, ...]
    filesystem_mode: FilesystemMode
    workspace: DeepAgentsWorkspace


_READ_ONLY_ERROR = "Permission denied: this filesystem namespace is read-only."


def _backend_result_types() -> tuple[Any, ...]:
    from deepagents.backends.protocol import (
        EditResult,
        FileDownloadResponse,
        FileUploadResponse,
        GlobResult,
        GrepResult,
        LsResult,
        ReadResult,
        WriteResult,
    )

    return (
        EditResult,
        FileDownloadResponse,
        FileUploadResponse,
        GlobResult,
        GrepResult,
        LsResult,
        ReadResult,
        WriteResult,
    )


class EmptyReadOnlyBackend:
    """A consumer-local empty backend that never reads LangGraph state."""

    def ls(self, path: str) -> Any:
        *_, LsResult, _, _ = _backend_result_types()
        return LsResult(entries=[] if path == "/" else None, error=None if path == "/" else "Path not found")

    async def als(self, path: str) -> Any:
        return self.ls(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> Any:
        del offset, limit
        *_, ReadResult, _ = _backend_result_types()
        return ReadResult(error=f"File not found: {file_path}")

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> Any:
        return self.read(file_path, offset, limit)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> Any:
        del pattern, path, glob
        _, _, _, _, GrepResult, *_ = _backend_result_types()
        return GrepResult(matches=[])

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> Any:
        return self.grep(pattern, path, glob)

    def glob(self, pattern: str, path: str | None = None) -> Any:
        del pattern, path
        _, _, _, GlobResult, *_ = _backend_result_types()
        return GlobResult(matches=[])

    async def aglob(self, pattern: str, path: str | None = None) -> Any:
        return self.glob(pattern, path)

    def write(self, file_path: str, content: str) -> Any:
        del file_path, content
        *_, WriteResult = _backend_result_types()
        return WriteResult(error=_READ_ONLY_ERROR)

    async def awrite(self, file_path: str, content: str) -> Any:
        return self.write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Any:
        del file_path, old_string, new_string, replace_all
        EditResult, *_ = _backend_result_types()
        return EditResult(error=_READ_ONLY_ERROR)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> Any:
        return self.edit(file_path, old_string, new_string, replace_all)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        _, _, FileUploadResponse, *_ = _backend_result_types()
        return [
            FileUploadResponse(path=path, error="permission_denied")
            for path, _ in files
        ]

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        return self.upload_files(files)

    def download_files(self, paths: list[str]) -> list[Any]:
        _, FileDownloadResponse, *_ = _backend_result_types()
        return [
            FileDownloadResponse(path=path, error="file_not_found")
            for path in paths
        ]

    async def adownload_files(self, paths: list[str]) -> list[Any]:
        return self.download_files(paths)


class ScopedSkillsBackend(EmptyReadOnlyBackend):
    """A read-only view containing only one consumer's selected Skills."""

    def __init__(self, readable_backend: Any) -> None:
        self._readable_backend = readable_backend

    def ls(self, path: str) -> Any:
        return self._readable_backend.ls(path)

    async def als(self, path: str) -> Any:
        return await self._readable_backend.als(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> Any:
        return self._readable_backend.read(file_path, offset=offset, limit=limit)

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000
    ) -> Any:
        return await self._readable_backend.aread(
            file_path, offset=offset, limit=limit
        )

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> Any:
        return self._readable_backend.grep(pattern, path, glob)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> Any:
        return await self._readable_backend.agrep(pattern, path, glob)

    def glob(self, pattern: str, path: str | None = None) -> Any:
        return self._readable_backend.glob(pattern, path)

    async def aglob(self, pattern: str, path: str | None = None) -> Any:
        return await self._readable_backend.aglob(pattern, path)

    def download_files(self, paths: list[str]) -> list[Any]:
        return self._readable_backend.download_files(paths)

    async def adownload_files(self, paths: list[str]) -> list[Any]:
        return await self._readable_backend.adownload_files(paths)


def _load_deepagents() -> tuple[Any, ...]:
    try:
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
        from deepagents.backends.utils import create_file_data
        from deepagents.middleware import FilesystemMiddleware, SkillsMiddleware
    except ImportError as exc:
        raise DeepAgentsCapabilityError(
            "The required DeepAgents runtime dependency is not installed"
        ) from exc
    return (
        CompositeBackend,
        FilesystemBackend,
        StateBackend,
        create_file_data,
        FilesystemMiddleware,
        SkillsMiddleware,
    )


def _virtual_join(prefix: str, suffix: str) -> str:
    base = prefix.rstrip("/")
    tail = suffix.replace("\\", "/").lstrip("/")
    return f"{base}/{tail}" if base else f"/{tail}"


def _file_data_from_path(filepath: Path, create_file_data: Any) -> Any:
    _assert_plain_source(filepath)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(filepath, flags)
    except OSError as exc:
        raise DeepAgentsCapabilityError(
            f"virtual file source cannot be opened safely: {filepath}"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DeepAgentsCapabilityError(
                f"virtual file source is not a regular file: {filepath}"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            content = source.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        return create_file_data(content.decode("utf-8"))
    except UnicodeDecodeError:
        return create_file_data(
            base64.b64encode(content).decode("ascii"),
            encoding="base64",
        )


def _source_stat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise DeepAgentsCapabilityError(
            f"virtual source cannot be inspected safely: {path}"
        ) from exc


def _assert_plain_source(path: Path) -> os.stat_result:
    source_stat = _source_stat(path)
    file_attributes = getattr(source_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(source_stat.st_mode) or (
        reparse_flag and file_attributes & reparse_flag
    ):
        raise DeepAgentsCapabilityError(
            f"virtual source links and reparse points are not supported: {path}"
        )
    return source_stat


def _walk_plain_sources(directory: Path) -> Iterator[Path]:
    directory_stat = _assert_plain_source(directory)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise DeepAgentsCapabilityError(
            f"virtual directory source_path is not a directory: {directory}"
        )
    try:
        with os.scandir(directory) as scanner:
            entries = sorted(scanner, key=lambda item: item.name)
    except OSError as exc:
        raise DeepAgentsCapabilityError(
            f"virtual directory source cannot be read safely: {directory}"
        ) from exc
    for entry in entries:
        filepath = Path(entry.path)
        source_stat = _assert_plain_source(filepath)
        if stat.S_ISDIR(source_stat.st_mode):
            yield filepath
            yield from _walk_plain_sources(filepath)
        elif stat.S_ISREG(source_stat.st_mode):
            yield filepath


def _seed_virtual_sources(
    block: FilesystemBlock,
    create_file_data: Any,
) -> dict[str, Any]:
    seeded: dict[str, Any] = {}
    origins: dict[str, Path] = {}
    directory_origins: dict[str, Path] = {}

    for binding in block.virtual_directories:
        source = Path(binding.source_path)
        source_stat = _assert_plain_source(source)
        if not stat.S_ISDIR(source_stat.st_mode):
            raise DeepAgentsCapabilityError(
                f"virtual directory source_path is not a directory: {source}"
            )
        directory_key = binding.virtual_path.rstrip("/")
        if directory_key in directory_origins:
            raise DeepAgentsCapabilityError(
                "virtual directory target conflicts: "
                f"{binding.virtual_path} ({directory_origins[directory_key]}, {source})"
            )
        directory_origins[directory_key] = source
        for filepath in _walk_plain_sources(source):
            relative = filepath.relative_to(source).as_posix()
            target = _virtual_join(binding.virtual_path, relative)
            source_stat = _assert_plain_source(filepath)
            if stat.S_ISDIR(source_stat.st_mode):
                if target in seeded:
                    raise DeepAgentsCapabilityError(
                        f"virtual target cannot be both file and directory: {target}"
                    )
                if target in directory_origins:
                    raise DeepAgentsCapabilityError(
                        "virtual directory target conflicts: "
                        f"{target}/ ({directory_origins[target]}, {filepath})"
                    )
                directory_origins[target] = filepath
                continue
            if not stat.S_ISREG(source_stat.st_mode):
                continue
            if target in directory_origins:
                raise DeepAgentsCapabilityError(
                    f"virtual target cannot be both file and directory: {target}"
                )
            if target in seeded:
                raise DeepAgentsCapabilityError(
                    f"virtual file target conflicts: {target} ({origins[target]}, {filepath})"
                )
            seeded[target] = _file_data_from_path(filepath, create_file_data)
            origins[target] = filepath

    for binding in block.virtual_files:
        source = Path(binding.source_path)
        source_stat = _assert_plain_source(source)
        if not stat.S_ISREG(source_stat.st_mode):
            raise DeepAgentsCapabilityError(
                f"virtual file source_path is not a file: {source}"
            )
        if PurePosixPath(binding.virtual_path).name != source.name:
            raise DeepAgentsCapabilityError(
                "virtual file name must match source file name: "
                f"{binding.virtual_path}, {source.name}"
            )
        if binding.virtual_path in directory_origins:
            raise DeepAgentsCapabilityError(
                "virtual target cannot be both file and directory: "
                f"{binding.virtual_path}"
            )
        if binding.virtual_path in seeded:
            raise DeepAgentsCapabilityError(
                "virtual file target conflicts: "
                f"{binding.virtual_path} ({origins[binding.virtual_path]}, {source})"
            )
        seeded[binding.virtual_path] = _file_data_from_path(source, create_file_data)
        origins[binding.virtual_path] = source
    return seeded


def _route_paths_overlap(left: str, right: str) -> bool:
    return left.startswith(right) or right.startswith(left)


def build_deepagents_capabilities(
    filesystem: FilesystemBlock | None,
    skill: SkillBlock | None,
    *,
    filesystem_permissions: FilesystemPermissionsBlock | None = None,
    filesystem_mode: FilesystemMode,
    skills_dir: Path,
    skill_owner_id: str = "",
    workspace: DeepAgentsWorkspace | None = None,
    mapped_directory_paths: Mapping[str, Path] | None = None,
) -> DeepAgentsCapabilities:
    """Compile one Agent's policy against a request-level shared workspace."""
    (
        CompositeBackend,
        FilesystemBackend,
        StateBackend,
        create_file_data,
        FilesystemMiddleware,
        SkillsMiddleware,
    ) = _load_deepagents()

    if filesystem_mode == "configured-shared" and filesystem is None:
        raise DeepAgentsCapabilityError("configured filesystem mode requires a block")
    if filesystem_mode == "default-shared" and filesystem is not None:
        raise DeepAgentsCapabilityError(
            "default filesystem mode does not accept a filesystem block"
        )

    if filesystem is not None:
        tool_configs = filesystem.tool_configs.model_dump()
    else:
        tool_configs = {
            name: {
                "visible": name in MINIMAL_FILESYSTEM_TOOL_NAMES,
                "description_override": None,
            }
            for name in FILESYSTEM_TOOL_NAMES
        }
    if filesystem_permissions is not None:
        for name, override in filesystem_permissions.tool_overrides:
            if override is not None:
                tool_configs[name] = override.model_dump()
    custom_tool_descriptions = {
        name: config["description_override"]
        for name, config in tool_configs.items()
        if config["description_override"] is not None
    }

    selected_skills: tuple[str, ...] = ()
    skill_sources: list[str] = []
    skill_package_root: Path | None = None
    if skill is not None:
        if skill.skill_package.folder != skill_owner_id:
            raise DeepAgentsCapabilityError(
                "Skill package folder does not match its owner configuration."
            )
        canonical_skills_root = skills_dir.resolve()
        candidate_root = canonical_skills_root / skill.skill_package.folder
        if os.path.lexists(candidate_root) and not is_plain_tree(candidate_root):
            raise DeepAgentsCapabilityError(
                "Skill package contains a link, reparse point, or special file."
            )
        try:
            candidate_root.resolve(strict=False).relative_to(canonical_skills_root)
        except ValueError as exc:
            raise DeepAgentsCapabilityError(
                "Skill package path escapes the active repository."
            ) from exc
        if candidate_root.is_dir():
            skill_package_root = candidate_root
            selected_skills = tuple(
                child.name
                for child in sorted(
                    candidate_root.iterdir(), key=lambda path: path.name.casefold()
                )
                if child.is_dir()
            )
            if selected_skills:
                skill_sources.append("/skills/")

    agent_routes: dict[str, Any] = {}
    for route in filesystem.mapped_directories if filesystem is not None else ():
        local_path = (
            mapped_directory_paths.get(route.virtual_path)
            if mapped_directory_paths is not None
            else Path(route.local_path)
        )
        if local_path is None:
            raise DeepAgentsCapabilityError(
                "resolved mapped directory is missing: "
                f"{route.virtual_path}"
            )
        if not local_path.is_dir():
            raise DeepAgentsCapabilityError(
                f"mapped local_path is not a directory: {local_path}"
            )
        agent_routes[route.virtual_path] = FilesystemBackend(
            root_dir=local_path,
            virtual_mode=True,
        )
    initial_files = (
        _seed_virtual_sources(filesystem, create_file_data)
        if filesystem is not None
        else {}
    )
    workspace = DeepAgentsWorkspace(
        default_backend=(
            workspace.default_backend if workspace is not None else StateBackend()
        ),
        routes=agent_routes,
        initial_files=initial_files,
    )

    conflicting_route = next(
        (path for path in workspace.routes if _route_paths_overlap(path, "/skills/")),
        None,
    )
    if conflicting_route is not None:
        raise DeepAgentsCapabilityError(
            "filesystem route conflicts with selected skill: "
            f"{conflicting_route}, /skills/"
        )
    hidden_file = next(
        (
            path
            for path in workspace.initial_files
            if path.startswith("/skills/")
        ),
        None,
    )
    if hidden_file is not None:
        raise DeepAgentsCapabilityError(
            f"virtual file target conflicts with selected skill: {hidden_file}"
        )

    skill_routes: dict[str, Any] = {}
    if skill_package_root is not None:
        skill_routes["/"] = FilesystemBackend(
            root_dir=skill_package_root,
            virtual_mode=True,
        )

    routes = dict(workspace.routes)
    routes["/skills/"] = ScopedSkillsBackend(
        CompositeBackend(default=EmptyReadOnlyBackend(), routes=skill_routes)
    )
    backend = CompositeBackend(default=workspace.default_backend, routes=routes)
    filesystem_kwargs: dict[str, Any] = {
        "backend": backend,
        "custom_tool_descriptions": custom_tool_descriptions or None,
        "tool_token_limit_before_evict": (
            filesystem.tool_token_limit_before_evict
            if filesystem is not None
            else None
        ),
        "human_message_token_limit_before_evict": (
            filesystem.human_message_token_limit_before_evict
            if filesystem is not None
            else None
        ),
        "grep_max_count": filesystem.grep_max_count if filesystem is not None else 1_000,
        "max_execute_timeout": (
            filesystem.max_execute_timeout if filesystem is not None else 3_600
        ),
    }
    filesystem_kwargs["tools"] = [
        name for name, config in tool_configs.items() if config["visible"]
    ]
    if (
        filesystem_permissions is not None
        and filesystem_permissions.system_prompt_override is not None
    ):
        filesystem_kwargs["system_prompt"] = (
            filesystem_permissions.system_prompt_override.value
        )
    elif filesystem is not None and filesystem.system_prompt_override is not None:
        filesystem_kwargs["system_prompt"] = filesystem.system_prompt_override
    materialized_permissions: list[Any] = []
    if filesystem_permissions is not None:
        from deepagents.middleware.filesystem import FilesystemPermission

        # Skill visibility is owned by the per-Agent skill route, not user rules.
        materialized_permissions.extend(
            (
                FilesystemPermission(
                    operations=["read"],
                    paths=["/skills/**"],
                    mode="allow",
                ),
                FilesystemPermission(
                    operations=["write"],
                    paths=["/skills/**"],
                    mode="deny",
                ),
            )
        )
        for entry in filesystem_permissions.permissions:
            if entry.permission == "read-write":
                materialized_permissions.append(
                    FilesystemPermission(
                        operations=["read", "write"],
                        paths=[entry.path],
                        mode="allow",
                    )
                )
            elif entry.permission == "read-only":
                materialized_permissions.extend(
                    (
                        FilesystemPermission(
                            operations=["read"],
                            paths=[entry.path],
                            mode="allow",
                        ),
                        FilesystemPermission(
                            operations=["write"],
                            paths=[entry.path],
                            mode="deny",
                        ),
                    )
                )
            else:
                materialized_permissions.append(
                    FilesystemPermission(
                        operations=["read", "write"],
                        paths=[entry.path],
                        mode="deny",
                    )
                )
        filesystem_kwargs["_permissions"] = materialized_permissions
    filesystem_middleware = FilesystemMiddleware(**filesystem_kwargs)
    middleware: list[Any] = []
    if skill_sources:
        skill_kwargs: dict[str, Any] = {
            "backend": backend,
            "sources": skill_sources,
        }
        if not skill.system_prompt_enabled:
            skill_kwargs["system_prompt"] = None
        elif skill.instruction_override is not None:
            skill_kwargs["system_prompt"] = skill.instruction_override
        middleware.append(SkillsMiddleware(**skill_kwargs))
    middleware.append(filesystem_middleware)

    return DeepAgentsCapabilities(
        backend=backend,
        middleware=tuple(middleware),
        initial_files=dict(workspace.initial_files),
        selected_skills=selected_skills,
        skill_sources=tuple(skill_sources),
        permissions=tuple(materialized_permissions),
        filesystem_mode=filesystem_mode,
        workspace=workspace,
    )
