from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import tempfile

from agent_shell.storage.permissions import secure_file


def _write_bytes_atomic(
    path: Path,
    content: bytes,
    *,
    skip_if_unchanged: bool = True,
    prepare_temporary: Callable[[Path], None] | None = None,
) -> None:
    """Replace one file atomically with bytes staged beside the destination."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if skip_if_unchanged:
        try:
            if path.read_bytes() == content:
                return
        except OSError:
            pass

    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        if prepare_temporary is not None:
            prepare_temporary(temporary)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_bytes_atomic(
    path: Path,
    content: bytes,
    *,
    skip_if_unchanged: bool = True,
) -> None:
    """Replace one file atomically with bytes staged beside the destination."""

    _write_bytes_atomic(
        path,
        content,
        skip_if_unchanged=skip_if_unchanged,
    )


def write_text_atomic(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    skip_if_unchanged: bool = True,
) -> None:
    write_bytes_atomic(
        path,
        content.encode(encoding),
        skip_if_unchanged=skip_if_unchanged,
    )


def write_private_text_atomic(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    skip_if_unchanged: bool = True,
) -> None:
    """Replace one sensitive text document without publishing a permissive file."""

    def require_private(temporary: Path) -> None:
        permission = secure_file(temporary)
        if not permission.enforced:
            raise PermissionError("The sensitive temporary file is not private.")

    _write_bytes_atomic(
        path,
        content.encode(encoding),
        skip_if_unchanged=skip_if_unchanged,
        prepare_temporary=require_private,
    )


__all__ = ["write_bytes_atomic", "write_private_text_atomic", "write_text_atomic"]
