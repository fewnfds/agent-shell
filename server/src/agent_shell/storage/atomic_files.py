from __future__ import annotations

import os
from pathlib import Path
import tempfile


def write_bytes_atomic(
    path: Path,
    content: bytes,
    *,
    skip_if_unchanged: bool = True,
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

    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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


__all__ = ["write_bytes_atomic", "write_text_atomic"]
