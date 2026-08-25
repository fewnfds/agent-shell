from __future__ import annotations

from pathlib import Path

import pytest

from agent_shell.storage import atomic_files
from agent_shell.storage.atomic_files import (
    write_bytes_atomic,
    write_private_text_atomic,
    write_text_atomic,
)
from agent_shell.storage.permissions import PermissionStatus
from agent_shell.storage.owned_paths import (
    OwnedPathError,
    is_plain_tree,
    is_reparse_point,
    require_data_root_relative_path,
    require_single_path_segment,
    resolve_data_root_relative_path,
    resolve_owned_relative_path,
)


def test_atomic_file_replace_preserves_previous_content_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "nested" / "record.txt"
    write_text_atomic(path, "before\n")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        write_bytes_atomic(path, b"after\n")

    assert path.read_text(encoding="utf-8") == "before\n"
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_private_atomic_replace_keeps_previous_file_when_permissions_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "agent-shell.env"
    path.write_text("before\n", encoding="utf-8")

    def reject_permissions(temporary: Path) -> PermissionStatus:
        assert temporary.stat().st_size == 0
        return PermissionStatus("file", False, "fixture", "fixture")

    monkeypatch.setattr(atomic_files, "secure_file", reject_permissions)

    with pytest.raises(PermissionError, match="temporary file is not private"):
        write_private_text_atomic(path, "after\n")

    assert path.read_text(encoding="utf-8") == "before\n"
    assert list(tmp_path.glob(".agent-shell.env.*.tmp")) == []


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "nested/name", "nested\\name", "C:relative"],
)
def test_single_path_segment_rejects_path_syntax(value: str) -> None:
    with pytest.raises(OwnedPathError):
        require_single_path_segment(value, label="owner")


def test_owned_relative_path_returns_normalized_path_inside_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "owned"
    root.mkdir()

    path, normalized = resolve_owned_relative_path(root, "folder/main.py")

    assert path == root / "folder" / "main.py"
    assert normalized == "folder/main.py"


@pytest.mark.parametrize(
    "value",
    [
        "C:relative",
        "C:/absolute",
        "C:\\absolute",
        "\\\\server\\share",
        "/absolute",
        ".",
        "..",
        "folder/../outside",
        "folder\\..\\outside",
    ],
)
def test_data_root_relative_path_rejects_drive_root_and_dot_segments(
    value: str,
) -> None:
    with pytest.raises(OwnedPathError):
        require_data_root_relative_path(value)


def test_data_root_relative_path_resolves_a_missing_nested_target(
    tmp_path: Path,
) -> None:
    assert resolve_data_root_relative_path(tmp_path, "files/missing") == (
        tmp_path / "files" / "missing"
    ).resolve()


@pytest.mark.parametrize(
    "value",
    ["../outside", "folder/../outside", "/absolute", "folder\\main.py"],
)
def test_owned_relative_path_rejects_non_normalized_or_escaping_path(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(OwnedPathError):
        resolve_owned_relative_path(tmp_path, value)


def test_reparse_detection_uses_windows_file_attributes() -> None:
    class ReparsePath:
        @staticmethod
        def lstat():
            return type(
                "Metadata",
                (),
                {"st_mode": 0, "st_file_attributes": 0x400},
            )()

    assert is_reparse_point(ReparsePath()) is True  # type: ignore[arg-type]


def test_plain_tree_rejects_a_detected_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    root.joinpath("linked").write_text("content", encoding="utf-8")
    monkeypatch.setattr(
        "agent_shell.storage.owned_paths.is_reparse_point",
        lambda path: Path(path).name == "linked",
    )

    assert is_plain_tree(root) is False
