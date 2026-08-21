from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat


class OwnedPathError(ValueError):
    pass


def is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def is_plain_tree(root: Path) -> bool:
    """Return whether a directory tree contains only plain directories and files."""

    pending = [Path(root)]
    try:
        while pending:
            directory = pending.pop()
            metadata = directory.lstat()
            if is_reparse_point(directory) or not stat.S_ISDIR(metadata.st_mode):
                return False
            with os.scandir(directory) as scanner:
                entries = list(scanner)
            for entry in entries:
                path = Path(entry.path)
                metadata = path.lstat()
                if is_reparse_point(path):
                    return False
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif not stat.S_ISREG(metadata.st_mode):
                    return False
    except OSError:
        return False
    return True


def require_single_path_segment(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise OwnedPathError(f"{label} must be one non-empty path segment")
    if (
        "/" in value
        or "\\" in value
        or "\x00" in value
        or PureWindowsPath(value).drive
    ):
        raise OwnedPathError(f"{label} must be one non-empty path segment")
    return value


def require_data_root_relative_path(
    value: object,
    *,
    label: str = "data-root-relative path",
) -> str:
    """Validate a host path that must be interpreted beneath the instance data root."""

    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "\x00" in value
        or ":" in value
    ):
        raise OwnedPathError(f"{label} must be relative to the instance data root")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if windows.drive or windows.root or posix.is_absolute():
        raise OwnedPathError(f"{label} must be relative to the instance data root")
    if any(
        part in {".", ".."}
        for path in (windows, posix)
        for part in path.parts
    ):
        raise OwnedPathError(f"{label} must not contain . or .. segments")
    return value


def resolve_data_root_relative_path(
    data_root: Path,
    value: object,
    *,
    label: str = "data-root-relative path",
) -> Path:
    relative = require_data_root_relative_path(value, label=label)
    root = Path(data_root).resolve()
    resolved = (root / Path(relative)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OwnedPathError(f"{label} escapes the instance data root") from exc
    return resolved


def resolve_owned_relative_path(
    root: Path,
    value: object,
    *,
    label: str = "relative path",
    allow_root: bool = False,
) -> tuple[Path, str]:
    """Resolve one normalized POSIX path without following an owned-tree link."""

    if not isinstance(value, str):
        raise OwnedPathError(f"{label} must be a normalized relative POSIX path")
    if value == "":
        if not allow_root:
            raise OwnedPathError(f"{label} must not be empty")
        normalized = ""
        parts: tuple[str, ...] = ()
    else:
        if "\\" in value or PureWindowsPath(value).drive:
            raise OwnedPathError(f"{label} must be a normalized relative POSIX path")
        pure = PurePosixPath(value)
        parts = pure.parts
        if (
            pure.is_absolute()
            or not parts
            or value != "/".join(parts)
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise OwnedPathError(f"{label} must be a normalized relative POSIX path")
        for part in parts:
            require_single_path_segment(part, label=label)
        normalized = "/".join(parts)

    root = Path(root)
    if os.path.lexists(root) and is_reparse_point(root):
        raise OwnedPathError(f"{label} root must not be a link or reparse point")
    canonical_root = root.resolve()
    current = canonical_root
    for part in parts:
        current = current / part
        if os.path.lexists(current) and is_reparse_point(current):
            raise OwnedPathError(f"{label} must not contain links or reparse points")
    try:
        current.resolve(strict=False).relative_to(canonical_root)
    except ValueError as exc:
        raise OwnedPathError(f"{label} escapes its owned root") from exc
    return current, normalized


__all__ = [
    "OwnedPathError",
    "is_plain_tree",
    "is_reparse_point",
    "require_data_root_relative_path",
    "require_single_path_segment",
    "resolve_data_root_relative_path",
    "resolve_owned_relative_path",
]
