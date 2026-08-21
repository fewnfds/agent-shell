from __future__ import annotations

import os
from pathlib import Path
import sqlite3

import pytest

from agent_shell.storage import permissions
from agent_shell.storage.database import SQLiteDatabase
from agent_shell.storage.permissions import (
    secure_database_files,
    secure_directory,
    secure_file,
)


def test_windows_private_dacl_allows_only_owner_and_trusted_system_sids() -> None:
    owner_sid = "S-1-5-21-1000"
    private_dacl = (
        f"D:P(A;;FA;;;{owner_sid})"
        "(A;;FA;;;S-1-5-18)"
        "(A;;FA;;;S-1-5-32-544)"
    )

    assert permissions._windows_dacl_is_private(private_dacl, owner_sid) is True
    assert (
        permissions._windows_dacl_is_private(
            private_dacl + "(A;;FR;;;S-1-5-32-545)", owner_sid
        )
        is False
    )
    assert (
        permissions._windows_dacl_is_private(
            "D:P(A;;FA;;;S-1-5-18)", owner_sid
        )
        is False
    )
    assert (
        permissions._windows_dacl_is_private(
            "D:PAI(A;;FA;;;LA)", "S-1-5-21-1000-500"
        )
        is True
    )
    assert (
        permissions._windows_dacl_is_private("D:PAI(A;;FA;;;LA)", owner_sid)
        is False
    )
    assert (
        permissions._windows_dacl_is_private(
            f"D:P(A;;FA;;;{owner_sid})(A;;FA;;;SY)(A;;FA;;;BA)", owner_sid
        )
        is True
    )


def test_windows_acl_descriptor_decodes_supported_icacls_encodings() -> None:
    descriptor = "fixture\r\nD:P(A;;FA;;;S-1-5-21-1000)\r\n"

    assert permissions._decode_windows_acl_descriptor(
        descriptor.encode("utf-16")
    ) == descriptor
    assert permissions._decode_windows_acl_descriptor(
        descriptor.encode("utf-16-le")
    ) == descriptor
    assert permissions._decode_windows_acl_descriptor(
        descriptor.encode("utf-8")
    ) == descriptor


def test_windows_acl_reader_separates_sacl_from_dacl() -> None:
    descriptor = "fixture\r\nD:PAI(A;;FA;;;LA)S:PAINO_ACCESS_CONTROL\r\n"

    assert permissions._extract_windows_dacl(descriptor) == "D:PAI(A;;FA;;;LA)"


def test_windows_acl_powershell_uses_only_system_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows_directory = Path("C:/Windows")
    monkeypatch.setenv("WINDIR", str(windows_directory))
    monkeypatch.setenv("PSModulePath", "C:/Program Files/PowerShell/7/Modules")

    environment = permissions._windows_powershell_environment()

    assert environment["PSModulePath"] == str(
        windows_directory
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "Modules"
    )


def test_windows_sid_resolution_ignores_non_utf8_account_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = "S-1-5-21-1000"
    output = b'"\xd3\xc3\xbb\xa7","' + sid.encode("ascii") + b'"\r\n'
    monkeypatch.setattr(permissions, "_windows_sid", None)
    monkeypatch.setattr(
        permissions.subprocess,
        "run",
        lambda command, **_: permissions.subprocess.CompletedProcess(
            command, 0, output
        ),
    )

    assert permissions._current_windows_sid() == sid


def test_private_directory_and_file_permissions_are_verified(tmp_path: Path) -> None:
    private = tmp_path / "private"
    directory_status = secure_directory(private)
    file_path = private / "authoring.sqlite3"
    file_path.write_bytes(b"sqlite fixture")
    file_status = secure_file(file_path)

    assert directory_status.enforced is True
    assert file_status.enforced is True
    if os.name == "nt":
        assert directory_status.mechanism == "windows-acl"
        assert file_status.mechanism == "windows-acl"
    else:
        assert directory_status.mechanism == "posix-mode-0700"
        assert file_status.mechanism == "posix-mode-0600"
        assert private.stat().st_mode & 0o077 == 0
        assert file_path.stat().st_mode & 0o077 == 0


def test_database_main_wal_and_shm_receive_same_file_policy(tmp_path: Path) -> None:
    private = tmp_path / "private"
    secure_directory(private)
    database = private / "authoring.sqlite3"
    candidates = (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
    )
    for candidate in candidates:
        candidate.write_bytes(b"fixture")

    statuses = secure_database_files(database)

    assert len(statuses) == 3
    assert all(status.enforced for status in statuses)


def test_database_transaction_commits_on_success(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "private" / "transaction.sqlite3")

    with database.transaction() as connection:
        connection.execute("CREATE TABLE transaction_fixture (value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO transaction_fixture (value) VALUES (?)", ("committed",)
        )

    with database.transaction() as connection:
        value = connection.execute(
            "SELECT value FROM transaction_fixture"
        ).fetchone()[0]
    assert value == "committed"


def test_database_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "private" / "rollback.sqlite3")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE rollback_fixture (value TEXT NOT NULL)")

    with pytest.raises(RuntimeError, match="rollback fixture"):
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO rollback_fixture (value) VALUES (?)", ("discarded",)
            )
            raise RuntimeError("rollback fixture")

    with database.transaction() as connection:
        count = connection.execute("SELECT COUNT(*) FROM rollback_fixture").fetchone()[0]
    assert count == 0


def test_database_transaction_closes_connection_after_exit(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "private" / "closed.sqlite3")

    with database.transaction() as connection:
        connection.execute("SELECT 1").fetchone()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
