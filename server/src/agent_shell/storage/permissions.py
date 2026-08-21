from __future__ import annotations

from dataclasses import dataclass
import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading


@dataclass(frozen=True, slots=True)
class PermissionStatus:
    path_kind: str
    enforced: bool
    mechanism: str
    boundary: str


_lock = threading.Lock()
_windows_sid: str | None = None
_WINDOWS_TRUSTED_SYSTEM_PRINCIPALS = frozenset(
    {
        "S-1-5-18",  # Local System
        "SY",  # Local System SDDL alias
        "S-1-5-32-544",  # Built-in Administrators
        "BA",  # Built-in Administrators SDDL alias
    }
)


def _windows_powershell_environment() -> dict[str, str]:
    environment = os.environ.copy()
    windows_directory = environment.get("WINDIR") or environment.get("SystemRoot")
    if windows_directory:
        environment["PSModulePath"] = str(
            Path(windows_directory)
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "Modules"
        )
    else:
        environment.pop("PSModulePath", None)
    return environment


def _current_windows_sid() -> str:
    global _windows_sid
    with _lock:
        if _windows_sid is not None:
            return _windows_sid
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return ""
        match = re.search(rb"S-\d+(?:-\d+)+", result.stdout or b"")
        _windows_sid = match.group(0).decode("ascii") if match else ""
        return _windows_sid


def _windows_dacl_is_private(dacl: str, sid: str) -> bool:
    principals = set(re.findall(r";;;([^;)]+)\)", dacl))
    owner_principals = {sid}
    if sid.endswith("-500"):
        owner_principals.add("LA")  # Local Administrator SDDL alias
    allowed_principals = _WINDOWS_TRUSTED_SYSTEM_PRINCIPALS | owner_principals
    return (
        dacl.startswith("D:P")
        and bool(principals & owner_principals)
        and principals <= allowed_principals
    )


def _decode_windows_acl_descriptor(payload: bytes) -> str:
    for encoding in ("utf-16", "utf-8-sig", "utf-16-le"):
        try:
            descriptor = payload.decode(encoding)
        except UnicodeError:
            continue
        if any(line.strip().startswith("D:") for line in descriptor.splitlines()):
            return descriptor
    return ""


def _extract_windows_dacl(descriptor: str) -> str:
    dacl = next(
        (
            line.strip()
            for line in descriptor.splitlines()
            if line.strip().startswith("D:")
        ),
        "",
    )
    return dacl.split("S:", maxsplit=1)[0]


def _read_windows_dacl(path: Path) -> str:
    descriptor_fd, descriptor_name = tempfile.mkstemp(
        prefix="agent-shell-acl-", suffix=".txt"
    )
    os.close(descriptor_fd)
    descriptor_path = Path(descriptor_name)
    descriptor_path.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            ["icacls", str(path), "/save", str(descriptor_path), "/q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return ""
        descriptor = _decode_windows_acl_descriptor(descriptor_path.read_bytes())
    except OSError:
        return ""
    finally:
        descriptor_path.unlink(missing_ok=True)
    return _extract_windows_dacl(descriptor)


def _windows_acl_is_private(path: Path, sid: str) -> bool:
    dacl = _read_windows_dacl(path)
    return _windows_dacl_is_private(dacl, sid)


def _replace_windows_acl(path: Path, sid: str, *, directory: bool) -> bool:
    inheritance = "OICI" if directory else ""
    sddl = f"O:{sid}G:{sid}D:P(A;{inheritance};FA;;;{sid})"
    script = (
        '$ErrorActionPreference="Stop";'
        "$acl=Get-Acl -LiteralPath $env:AGENT_SHELL_ACL_PATH;"
        "$acl.SetSecurityDescriptorSddlForm($env:AGENT_SHELL_ACL_SDDL);"
        "Set-Acl -LiteralPath $env:AGENT_SHELL_ACL_PATH -AclObject $acl"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    environment = _windows_powershell_environment()
    environment["AGENT_SHELL_ACL_PATH"] = str(path)
    environment["AGENT_SHELL_ACL_SDDL"] = sddl
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        env=environment,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0 and _windows_acl_is_private(path, sid)


def _secure_windows(path: Path, *, directory: bool) -> PermissionStatus:
    sid = _current_windows_sid()
    if not sid:
        return PermissionStatus(
            "directory" if directory else "file",
            False,
            "windows-acl-unavailable",
            "Current process account SID could not be resolved.",
        )
    grant = f"*{sid}:(OI)(CI)F" if directory else f"*{sid}:F"
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", grant, "/q"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    enforced = result.returncode == 0 and _windows_acl_is_private(path, sid)
    if not enforced:
        enforced = _replace_windows_acl(path, sid, directory=directory)
    return PermissionStatus(
        "directory" if directory else "file",
        enforced,
        "windows-acl" if enforced else "windows-acl-unconfirmed",
        (
            "The protected DACL contains only the current process account and "
            "trusted Windows system principals."
            if enforced
            else "The OS did not confirm a protected private DACL."
        ),
    )


def secure_directory(path: Path) -> PermissionStatus:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        return _secure_windows(path, directory=True)
    try:
        path.chmod(0o700)
    except OSError:
        return PermissionStatus(
            "directory",
            False,
            "posix-mode-failed",
            "The OS did not confirm mode 0700.",
        )
    return PermissionStatus(
        "directory",
        (path.stat().st_mode & 0o077) == 0,
        "posix-mode-0700",
        "Only the process account has directory permission bits.",
    )


def secure_file(path: Path) -> PermissionStatus:
    if not path.exists():
        return PermissionStatus(
            "file", False, "missing", "The file does not exist yet."
        )
    if os.name == "nt":
        return _secure_windows(path, directory=False)
    try:
        path.chmod(0o600)
    except OSError:
        return PermissionStatus(
            "file", False, "posix-mode-failed", "The OS did not confirm mode 0600."
        )
    return PermissionStatus(
        "file",
        (path.stat().st_mode & 0o077) == 0,
        "posix-mode-0600",
        "Only the process account has file permission bits.",
    )


def secure_database_files(path: Path) -> tuple[PermissionStatus, ...]:
    statuses: list[PermissionStatus] = []
    for candidate in (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    ):
        if candidate.exists():
            statuses.append(secure_file(candidate))
    return tuple(statuses)
