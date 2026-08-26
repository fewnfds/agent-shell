from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Mapping

from agent_shell.contracts import (
    FilesystemBlock,
    FilesystemPermissionValue,
    FilesystemToolsBlock,
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
        from deepagents.backends import (
            CompositeBackend,
            FilesystemBackend,
            LocalShellBackend,
            StateBackend,
        )
        from deepagents.backends.utils import create_file_data
        from deepagents.middleware import FilesystemMiddleware, SkillsMiddleware
    except ImportError as exc:
        raise DeepAgentsCapabilityError(
            "The required DeepAgents runtime dependency is not installed"
        ) from exc
    return (
        CompositeBackend,
        FilesystemBackend,
        LocalShellBackend,
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


def _permission_paths(path: str, *, is_directory: bool) -> list[str]:
    if not is_directory:
        return [path]
    return [path, f"{path.rstrip('/')}/**"]


def _append_permission(
    materialized: list[Any],
    permission_type: Any,
    *,
    path: str,
    is_directory: bool,
    permission: FilesystemPermissionValue,
) -> None:
    paths = _permission_paths(path, is_directory=is_directory)
    if permission == "read-write":
        materialized.append(
            permission_type(
                operations=["read", "write"], paths=paths, mode="allow"
            )
        )
    elif permission == "read-only":
        materialized.extend(
            (
                permission_type(operations=["read"], paths=paths, mode="allow"),
                permission_type(operations=["write"], paths=paths, mode="deny"),
            )
        )
    else:
        materialized.append(
            permission_type(
                operations=["read", "write"], paths=paths, mode="deny"
            )
        )


def build_deepagents_capabilities(
    filesystem: FilesystemBlock,
    skill: SkillBlock | None,
    *,
    filesystem_tools: FilesystemToolsBlock | None = None,
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
        LocalShellBackend,
        StateBackend,
        create_file_data,
        FilesystemMiddleware,
        SkillsMiddleware,
    ) = _load_deepagents()

    if filesystem.backend_type != filesystem_mode:
        raise DeepAgentsCapabilityError(
            "filesystem mode does not match the selected backend block"
        )

    filesystem_tools = filesystem_tools or FilesystemToolsBlock(
        name="Default filesystem tools"
    )
    tool_configs = filesystem_tools.tool_configs.model_dump()
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

    shared_default_backend = (
        workspace.default_backend if workspace is not None else StateBackend()
    )
    if filesystem_mode == "local-shell":
        if skill is not None:
            raise DeepAgentsCapabilityError(
                "LocalShellBackend does not accept a Skill package"
            )
        assert filesystem.workspace is not None
        workspace_root = (
            mapped_directory_paths.get("/")
            if mapped_directory_paths is not None
            else Path(filesystem.workspace.local_path)
        )
        if workspace_root is None or not workspace_root.is_dir():
            raise DeepAgentsCapabilityError(
                "resolved LocalShellBackend workspace is unavailable"
            )
        backend = LocalShellBackend(root_dir=workspace_root, virtual_mode=True)
        workspace = workspace or DeepAgentsWorkspace(
            default_backend=shared_default_backend,
            routes={},
            initial_files={},
        )
    else:
        agent_routes: dict[str, Any] = {}
        for route in filesystem.mapped_directories:
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
        initial_files = _seed_virtual_sources(filesystem, create_file_data)
        workspace = DeepAgentsWorkspace(
            default_backend=shared_default_backend,
            routes=agent_routes,
            initial_files=initial_files,
        )

        if skill_package_root is not None:
            conflicting_route = next(
                (
                    path
                    for path in workspace.routes
                    if _route_paths_overlap(path, "/skills/")
                ),
                None,
            )
            if conflicting_route is not None:
                raise DeepAgentsCapabilityError(
                    "filesystem route conflicts with selected Skill package: "
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
                    "virtual file target conflicts with selected Skill package: "
                    f"{hidden_file}"
                )

        routes = dict(workspace.routes)
        if skill_package_root is not None:
            routes["/skills/"] = ScopedSkillsBackend(
                CompositeBackend(
                    default=EmptyReadOnlyBackend(),
                    routes={
                        "/": FilesystemBackend(
                            root_dir=skill_package_root,
                            virtual_mode=True,
                        )
                    },
                )
            )
        backend = CompositeBackend(default=workspace.default_backend, routes=routes)

    filesystem_kwargs: dict[str, Any] = {
        "backend": backend,
        "custom_tool_descriptions": custom_tool_descriptions or None,
        "tool_token_limit_before_evict": (
            filesystem_tools.tool_token_limit_before_evict
        ),
        "human_message_token_limit_before_evict": (
            filesystem_tools.human_message_token_limit_before_evict
        ),
        "grep_max_count": filesystem_tools.grep_max_count,
        "max_execute_timeout": filesystem_tools.max_execute_timeout,
    }
    filesystem_kwargs["tools"] = [
        name
        for name, config in tool_configs.items()
        if config["visible"] and (name != "execute" or filesystem_mode == "local-shell")
    ]
    if filesystem.system_prompt_override is not None:
        filesystem_kwargs["system_prompt"] = filesystem.system_prompt_override
    materialized_permissions: list[Any] = []
    if filesystem_mode == "composite":
        from deepagents.middleware.filesystem import FilesystemPermission

        for source in filesystem.mapped_directories:
            _append_permission(
                materialized_permissions,
                FilesystemPermission,
                path=source.virtual_path,
                is_directory=True,
                permission=source.permission,
            )
        for source in filesystem.virtual_directories:
            _append_permission(
                materialized_permissions,
                FilesystemPermission,
                path=source.virtual_path,
                is_directory=True,
                permission=source.permission,
            )
        for source in filesystem.virtual_files:
            _append_permission(
                materialized_permissions,
                FilesystemPermission,
                path=source.virtual_path,
                is_directory=False,
                permission=source.permission,
            )
        if skill_package_root is not None:
            _append_permission(
                materialized_permissions,
                FilesystemPermission,
                path="/skills/",
                is_directory=True,
                permission="read-only",
            )
        if materialized_permissions:
            filesystem_kwargs["_permissions"] = materialized_permissions
    filesystem_middleware = FilesystemMiddleware(**filesystem_kwargs)
    middleware: list[Any] = []
    if skill_sources:
        assert skill is not None
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
