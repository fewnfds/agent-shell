from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import tempfile
from typing import Any, Literal
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from agent_shell.configuration.repositories import (
    CONFIGURATION_REPOSITORIES_DIRECTORY,
    PYTHON_PACKAGES_DIRECTORY,
    SKILL_PACKAGES_DIRECTORY,
    load_configuration_repository,
)
from agent_shell.storage.atomic_files import write_bytes_atomic
from agent_shell.storage.owned_paths import is_reparse_point


_TEMPORARY_PREFIX = ".agent-shell-write-"
_WINDOWS_INVALID_CHARACTERS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


async def _blocking_file_call(
    call: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Finish an in-flight file operation before propagating cancellation."""

    task = asyncio.create_task(asyncio.to_thread(call, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


def _create_upload_file(path: Path) -> None:
    with path.open("xb"):
        pass


def _append_upload_chunk(path: Path, chunk: bytes) -> None:
    with path.open("ab") as output:
        output.write(chunk)


def _commit_upload_file(temporary: Path, target: Path) -> None:
    with temporary.open("ab") as output:
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)


_DATA_CHILDREN = (
    "files",
    "skills-template",
    "templates",
    CONFIGURATION_REPOSITORIES_DIRECTORY,
)
_REPOSITORY_CHILDREN = (
    "components",
    "agents",
    "workflows",
    PYTHON_PACKAGES_DIRECTORY,
    SKILL_PACKAGES_DIRECTORY,
)
_EDITABLE_DATA_ROOTS = {"files", "skills-template", "templates"}
_EDITABLE_REPOSITORY_ROOTS = {
    PYTHON_PACKAGES_DIRECTORY,
    SKILL_PACKAGES_DIRECTORY,
}
_READ_ONLY_REPOSITORY_ROOTS = {"components", "agents", "workflows"}

AccessMode = Literal["navigation", "read-only", "editable"]
EntryKind = Literal["directory", "file", "unsupported"]


@dataclass(frozen=True, slots=True)
class FileDownload:
    path: Path
    filename: str
    media_type: str
    delete_after: bool = False


class FileManagerError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message_key: str,
        fallback: str,
        message_args: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message_key = message_key
        self.message_args = message_args or {}
        super().__init__(fallback)


class FileManagerService:
    """Expose approved instance-data trees through real data/... paths."""

    def __init__(
        self,
        data_root: Path,
        temporary_directory: Path,
    ) -> None:
        self._data_root = Path(data_root).resolve()
        self._temporary_directory = temporary_directory.resolve()

    @staticmethod
    def _validate_segment(segment: str) -> None:
        invalid = (
            not segment
            or segment in {".", ".."}
            or segment.startswith(_TEMPORARY_PREFIX)
            or segment.endswith((" ", "."))
            or any(ord(character) < 32 for character in segment)
            or any(character in _WINDOWS_INVALID_CHARACTERS for character in segment)
            or segment.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        )
        if invalid:
            raise FileManagerError(
                422,
                "file_path_invalid",
                "errors.filePathInvalid",
                "The file path is invalid.",
            )

    @staticmethod
    def _missing() -> FileManagerError:
        return FileManagerError(
            404,
            "file_not_found",
            "errors.fileNotFound",
            "The file or directory does not exist.",
        )

    @staticmethod
    def _denied() -> FileManagerError:
        return FileManagerError(
            403,
            "file_operation_denied",
            "errors.fileOperationDenied",
            "This operation is not available for the selected path.",
        )

    @staticmethod
    def _operation_failed() -> FileManagerError:
        return FileManagerError(
            409,
            "file_operation_failed",
            "errors.fileOperationFailed",
            "The file operation could not be completed.",
        )

    def _parts(self, value: object) -> tuple[str, ...]:
        if (
            not isinstance(value, str)
            or not value
            or "\\" in value
            or PureWindowsPath(value).drive
        ):
            raise FileManagerError(
                422,
                "file_path_invalid",
                "errors.filePathInvalid",
                "The file path must be a normalized data/... path.",
            )
        pure = PurePosixPath(value)
        parts = pure.parts
        if (
            pure.is_absolute()
            or not parts
            or value != "/".join(parts)
            or parts[0] != "data"
        ):
            raise FileManagerError(
                422,
                "file_path_invalid",
                "errors.filePathInvalid",
                "The file path must be a normalized data/... path.",
            )
        for segment in parts:
            self._validate_segment(segment)
        return parts

    def _repository_root(self, repository_name: str) -> Path:
        root = (
            self._data_root
            / CONFIGURATION_REPOSITORIES_DIRECTORY
            / repository_name
        )
        if not root.is_dir() or is_reparse_point(root):
            raise self._missing()
        try:
            descriptor = load_configuration_repository(root)
        except ValueError as exc:
            raise self._missing() from exc
        return descriptor.root

    def _access_mode(self, parts: tuple[str, ...]) -> AccessMode:
        if parts == ("data",):
            return "navigation"
        first = parts[1]
        if first in _EDITABLE_DATA_ROOTS:
            return "editable"
        if first != CONFIGURATION_REPOSITORIES_DIRECTORY:
            raise self._missing()
        if len(parts) == 2:
            return "navigation"
        self._repository_root(parts[2])
        if len(parts) == 3:
            return "navigation"
        root = parts[3]
        if root in _EDITABLE_REPOSITORY_ROOTS:
            return "editable"
        if root in _READ_ONLY_REPOSITORY_ROOTS:
            return "read-only"
        raise self._missing()

    def _path(self, value: object) -> tuple[Path, str, tuple[str, ...], AccessMode]:
        parts = self._parts(value)
        target = self._data_root.joinpath(*parts[1:])
        current = self._data_root
        if os.path.lexists(current) and is_reparse_point(current):
            raise FileManagerError(
                422,
                "file_link_unsupported",
                "errors.fileLinkUnsupported",
                "Symbolic links and reparse points are not supported.",
            )
        for segment in parts[1:]:
            current = current / segment
            if os.path.lexists(current) and is_reparse_point(current):
                raise FileManagerError(
                    422,
                    "file_link_unsupported",
                    "errors.fileLinkUnsupported",
                    "Symbolic links and reparse points are not supported.",
                )
        try:
            target.resolve(strict=False).relative_to(self._data_root)
        except ValueError as exc:
            raise FileManagerError(
                422,
                "file_path_invalid",
                "errors.filePathInvalid",
                "The file path escapes the instance data root.",
            ) from exc
        mode = self._access_mode(parts)
        return target, "/".join(parts), parts, mode

    @staticmethod
    def _protected_root(parts: tuple[str, ...]) -> bool:
        return len(parts) == 2 or (
            len(parts) == 4
            and parts[1] == CONFIGURATION_REPOSITORIES_DIRECTORY
        )

    @classmethod
    def _capabilities(
        cls,
        parts: tuple[str, ...],
        mode: AccessMode,
        kind: EntryKind,
    ) -> dict[str, bool]:
        supported = kind != "unsupported"
        directory = kind == "directory"
        file = kind == "file"
        visible_content = mode != "navigation" and supported
        mutable = mode == "editable" and supported and not cls._protected_root(parts)
        return {
            "list": directory and supported,
            "read": file and visible_content,
            "create": directory and mode == "editable" and supported,
            "upload": directory and mode == "editable" and supported,
            "write": file and mode == "editable" and supported,
            "download": visible_content,
            "archive": visible_content,
            "rename": mutable,
            "delete": mutable,
        }

    def _kind(self, target: Path) -> EntryKind:
        try:
            metadata = target.lstat()
        except OSError as exc:
            raise self._missing() from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag):
            return "unsupported"
        if stat.S_ISDIR(metadata.st_mode):
            return "directory"
        if stat.S_ISREG(metadata.st_mode):
            return "file"
        return "unsupported"

    def capabilities(self, path: object) -> dict[str, bool]:
        target, _, parts, mode = self._path(path)
        return self._capabilities(parts, mode, self._kind(target))

    def _require(
        self,
        path: object,
        capability: str,
    ) -> tuple[Path, str, tuple[str, ...], AccessMode, EntryKind]:
        target, normalized, parts, mode = self._path(path)
        kind = self._kind(target)
        if not self._capabilities(parts, mode, kind).get(capability, False):
            raise self._denied()
        return target, normalized, parts, mode, kind

    def _visible_names(self, parts: tuple[str, ...]) -> set[str] | None:
        if parts == ("data",):
            return set(_DATA_CHILDREN)
        if parts == ("data", CONFIGURATION_REPOSITORIES_DIRECTORY):
            root = self._data_root / CONFIGURATION_REPOSITORIES_DIRECTORY
            if not root.exists():
                return set()
            result: set[str] = set()
            for child in root.iterdir():
                try:
                    self._repository_root(child.name)
                except FileManagerError:
                    continue
                result.add(child.name)
            return result
        if (
            len(parts) == 3
            and parts[1] == CONFIGURATION_REPOSITORIES_DIRECTORY
        ):
            return set(_REPOSITORY_CHILDREN)
        return None

    @staticmethod
    def _modified_at(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _metadata_revision(metadata: os.stat_result) -> str:
        return f"{metadata.st_mtime_ns:x}-{metadata.st_size:x}"

    @staticmethod
    def _content_revision(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def list_directory(self, path: str = "data") -> dict[str, Any]:
        directory, normalized, parts, mode = self._path(path)
        if not directory.exists():
            raise self._missing()
        if self._kind(directory) != "directory":
            raise FileManagerError(
                409,
                "file_not_directory",
                "errors.fileNotDirectory",
                "The selected path is not a directory.",
            )
        visible_names = self._visible_names(parts)
        items: list[dict[str, Any]] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.startswith(_TEMPORARY_PREFIX) or (
                        visible_names is not None and entry.name not in visible_names
                    ):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    attributes = getattr(metadata, "st_file_attributes", 0)
                    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    unsupported = entry.is_symlink() or bool(attributes & reparse_flag)
                    kind: EntryKind = (
                        "unsupported"
                        if unsupported
                        else "directory"
                        if entry.is_dir(follow_symlinks=False)
                        else "file"
                        if entry.is_file(follow_symlinks=False)
                        else "unsupported"
                    )
                    item_path = f"{normalized}/{entry.name}"
                    try:
                        item_parts = self._parts(item_path)
                        item_mode = self._access_mode(item_parts)
                        capabilities = self._capabilities(item_parts, item_mode, kind)
                    except FileManagerError:
                        continue
                    items.append(
                        {
                            "name": entry.name,
                            "path": item_path,
                            "kind": kind,
                            "size": metadata.st_size if kind == "file" else None,
                            "modified_at": self._modified_at(metadata.st_mtime),
                            "revision": self._metadata_revision(metadata),
                            "capabilities": capabilities,
                        }
                    )
        except OSError as exc:
            raise self._operation_failed() from exc
        items.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
        return {
            "path": normalized,
            "capabilities": self._capabilities(parts, mode, "directory"),
            "items": items,
        }

    def _creation_target(
        self, path: str, capability: str
    ) -> tuple[Path, str, tuple[str, ...], AccessMode]:
        target, normalized, parts, mode = self._path(path)
        if mode != "editable" or self._protected_root(parts):
            raise self._denied()
        parent_path = "/".join(parts[:-1])
        parent, _, _, parent_mode = self._path(parent_path)
        if parent_mode != "editable":
            raise self._denied()
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._operation_failed() from exc
        parent, _, _, parent_mode, parent_kind = self._require(
            parent_path, capability
        )
        if parent_kind != "directory" or target.parent != parent:
            raise self._denied()
        if parent_mode != "editable":
            raise self._denied()
        return target, normalized, parts, mode

    def create_directory(self, path: str) -> dict[str, Any]:
        target, normalized, _, _ = self._creation_target(path, "create")
        try:
            target.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise FileManagerError(
                409,
                "file_already_exists",
                "errors.fileAlreadyExists",
                "A file or directory already exists at the destination.",
            ) from exc
        except OSError as exc:
            raise self._operation_failed() from exc
        return {"path": normalized, "kind": "directory"}

    def create_text_file(self, path: str) -> dict[str, Any]:
        target, normalized, _, _ = self._creation_target(path, "create")
        try:
            with target.open("x", encoding="utf-8", newline=""):
                pass
        except FileExistsError as exc:
            raise FileManagerError(
                409,
                "file_already_exists",
                "errors.fileAlreadyExists",
                "A file or directory already exists at the destination.",
            ) from exc
        except OSError as exc:
            raise self._operation_failed() from exc
        return {
            "path": normalized,
            "kind": "file",
            "revision": self._content_revision(b""),
        }

    async def upload(
        self,
        path: str,
        chunks: AsyncIterable[bytes],
        *,
        overwrite: bool,
    ) -> dict[str, Any]:
        def prepare() -> tuple[Path, str]:
            target, normalized, _, _ = self._creation_target(path, "upload")
            if os.path.lexists(target) and is_reparse_point(target):
                raise FileManagerError(
                    422,
                    "file_link_unsupported",
                    "errors.fileLinkUnsupported",
                    "Symbolic links and reparse points are not supported.",
                )
            if target.exists() and not overwrite:
                raise FileManagerError(
                    409,
                    "file_already_exists",
                    "errors.fileAlreadyExists",
                    "A file or directory already exists at the destination.",
                )
            if target.exists() and not target.is_file():
                raise FileManagerError(
                    409,
                    "file_not_regular",
                    "errors.fileNotRegular",
                    "The selected path is not a regular file.",
                )
            return target, normalized

        target, normalized = await _blocking_file_call(prepare)
        temporary = target.parent / f"{_TEMPORARY_PREFIX}{uuid4().hex}.tmp"
        size = 0
        try:
            await _blocking_file_call(_create_upload_file, temporary)
            async for chunk in chunks:
                await _blocking_file_call(_append_upload_chunk, temporary, chunk)
                size += len(chunk)
            await _blocking_file_call(_commit_upload_file, temporary, target)
        except OSError as exc:
            await _blocking_file_call(temporary.unlink, missing_ok=True)
            raise self._operation_failed() from exc
        except BaseException:
            await _blocking_file_call(temporary.unlink, missing_ok=True)
            raise
        return {"path": normalized, "kind": "file", "size": size}

    def save_generated_file(self, path: str, content: bytes) -> dict[str, Any]:
        """Persist one program-generated user file through File Manager ownership."""
        target, normalized, _, _ = self._creation_target(path, "upload")
        if os.path.lexists(target):
            raise FileManagerError(
                409,
                "file_already_exists",
                "errors.fileAlreadyExists",
                "A file or directory already exists at the destination.",
            )
        try:
            write_bytes_atomic(target, content)
        except OSError as exc:
            raise self._operation_failed() from exc
        return {"path": normalized, "kind": "file", "size": len(content)}

    def _archive_targets(self, paths: list[str]) -> list[Path]:
        if not paths:
            raise FileManagerError(
                422,
                "file_selection_required",
                "errors.fileSelectionRequired",
                "Select at least one file or directory.",
            )
        targets: list[Path] = []
        selected_paths: set[Path] = set()
        archive_names: set[str] = set()
        for path in paths:
            target, _, _, _, _ = self._require(path, "archive")
            if target in selected_paths:
                continue
            if target.name in archive_names:
                raise FileManagerError(
                    422,
                    "file_archive_name_conflict",
                    "errors.fileArchiveNameConflict",
                    "Selected entries must have unique names.",
                )
            selected_paths.add(target)
            archive_names.add(target.name)
            targets.append(target)
        return targets

    def _archive_entries(
        self, target: Path
    ) -> Iterator[tuple[Path, str, bool, int]]:
        if target.is_file():
            try:
                metadata = target.stat()
            except OSError as exc:
                raise self._operation_failed() from exc
            yield target, target.name, False, metadata.st_size
            return
        yield target, f"{target.name}/", True, 0
        pending = [target]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as scanned:
                    entries = sorted(scanned, key=lambda item: item.name.casefold())
            except OSError as exc:
                raise self._operation_failed() from exc
            child_directories: list[Path] = []
            for entry in entries:
                if entry.name.startswith(_TEMPORARY_PREFIX):
                    continue
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise self._operation_failed() from exc
                attributes = getattr(metadata, "st_file_attributes", 0)
                reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if entry.is_symlink() or bool(attributes & reparse_flag):
                    raise FileManagerError(
                        422,
                        "file_link_unsupported",
                        "errors.fileLinkUnsupported",
                        "Symbolic links and reparse points are not supported.",
                    )
                path = Path(entry.path)
                archive_path = (
                    Path(target.name) / path.relative_to(target)
                ).as_posix()
                if entry.is_dir(follow_symlinks=False):
                    yield path, f"{archive_path}/", True, 0
                    child_directories.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path, archive_path, False, metadata.st_size
                else:
                    raise FileManagerError(
                        409,
                        "file_not_regular",
                        "errors.fileNotRegular",
                        "The selected path is not a regular file or directory.",
                    )
            pending.extend(reversed(child_directories))

    def preview_archive(self, paths: list[str]) -> dict[str, int]:
        total_size = 0
        file_count = 0
        directory_count = 0
        for target in self._archive_targets(paths):
            for _, _, is_directory, size in self._archive_entries(target):
                if is_directory:
                    directory_count += 1
                else:
                    file_count += 1
                    total_size += size
        return {
            "total_size": total_size,
            "file_count": file_count,
            "directory_count": directory_count,
        }

    def prepare_archive(self, paths: list[str]) -> FileDownload:
        targets = self._archive_targets(paths)
        try:
            self._temporary_directory.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=_TEMPORARY_PREFIX,
                suffix=".zip",
                dir=self._temporary_directory,
            )
        except OSError as exc:
            raise self._operation_failed() from exc
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with ZipFile(
                temporary,
                mode="w",
                compression=ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                for target in targets:
                    for path, archive_path, is_directory, _ in self._archive_entries(target):
                        if is_directory:
                            archive.writestr(archive_path, b"")
                        else:
                            archive.write(path, archive_path)
        except FileManagerError:
            temporary.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise self._operation_failed() from exc
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return FileDownload(
            path=temporary,
            filename=(
                f"{targets[0].name}.zip"
                if len(targets) == 1
                else "agent-shell-files.zip"
            ),
            media_type="application/zip",
            delete_after=True,
        )

    def prepare_download(self, path: str) -> FileDownload:
        target, normalized, _, _, kind = self._require(path, "download")
        if kind == "directory":
            return self.prepare_archive([normalized])
        if kind != "file":
            raise self._denied()
        return FileDownload(
            path=target,
            filename=target.name,
            media_type="application/octet-stream",
        )

    def release_download(self, download: FileDownload) -> None:
        if not download.delete_after:
            return
        path = download.path.resolve()
        if (
            path.parent != self._temporary_directory
            or not path.name.startswith(_TEMPORARY_PREFIX)
        ):
            raise ValueError("the download is not an owned temporary artifact")
        path.unlink(missing_ok=True)

    def _regular_file_path(
        self, path: str, capability: str
    ) -> tuple[Path, str]:
        target, normalized, _, _, kind = self._require(path, capability)
        if kind != "file":
            raise FileManagerError(
                409,
                "file_not_regular",
                "errors.fileNotRegular",
                "The selected path is not a regular file.",
            )
        return target, normalized

    def read_text(self, path: str) -> dict[str, Any]:
        target, normalized = self._regular_file_path(path, "read")
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise self._operation_failed() from exc
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileManagerError(
                415,
                "text_file_invalid_encoding",
                "errors.textFileInvalidEncoding",
                "The text editor supports UTF-8 files only.",
            ) from exc
        return {
            "path": normalized,
            "content": text,
            "revision": self._content_revision(content),
            "capabilities": self.capabilities(normalized),
        }

    def save_text(
        self,
        path: str,
        content: str,
        revision: str,
    ) -> dict[str, Any]:
        target, normalized = self._regular_file_path(path, "write")
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise self._operation_failed() from exc
        if self._content_revision(current) != revision:
            raise FileManagerError(
                409,
                "text_file_revision_conflict",
                "errors.textFileRevisionConflict",
                "The file changed after it was opened.",
            )
        encoded = content.encode("utf-8")
        try:
            write_bytes_atomic(target, encoded)
        except OSError as exc:
            raise self._operation_failed() from exc
        return {
            "path": normalized,
            "revision": self._content_revision(encoded),
        }

    def rename(self, path: str, name: str) -> dict[str, Any]:
        self._validate_segment(name)
        source, source_normalized, parts, _, _ = self._require(path, "rename")
        destination_normalized = "/".join((*parts[:-1], name))
        destination, _, _, destination_mode = self._path(destination_normalized)
        if destination_mode != "editable":
            raise self._denied()
        if destination == source:
            return {"source_path": source_normalized, "path": source_normalized}
        if os.path.lexists(destination):
            raise FileManagerError(
                409,
                "file_already_exists",
                "errors.fileAlreadyExists",
                "A file or directory already exists at the destination.",
            )
        try:
            os.replace(source, destination)
        except OSError as exc:
            raise self._operation_failed() from exc
        return {"source_path": source_normalized, "path": destination_normalized}

    def delete(self, path: str) -> dict[str, Any]:
        target, normalized, _, _, kind = self._require(path, "delete")
        try:
            if kind == "directory":
                shutil.rmtree(target)
            elif kind == "file":
                target.unlink()
            else:
                raise self._denied()
        except FileManagerError:
            raise
        except OSError as exc:
            raise self._operation_failed() from exc
        return {"path": normalized, "deleted": True}


__all__ = ["FileDownload", "FileManagerError", "FileManagerService"]
