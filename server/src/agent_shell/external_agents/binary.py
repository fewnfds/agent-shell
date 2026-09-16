"""Locate and verify the pinned Antigravity CLI executable.

``agy`` is not redistributed with agent-shell and has no license in its
release repository, so the runtime keeps its own pinned copy under
``runtime/antigravity/<version>/`` and verifies the official release hash
before every process starts. A different build is an explicit failure, never
a silent upgrade.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import platform
from pathlib import Path
import sys

from agent_shell.external_agents.errors import binary_unavailable
from agent_shell.runtime.errors import AgentRuntimeError


RUNTIME_DIRECTORY = "antigravity"
WINDOWS_X64 = "windows-x64"


@dataclass(frozen=True)
class AntigravityCliRelease:
    """One pinned upstream release and the artifact identity we accept."""

    version: str
    platform: str
    archive: str
    archive_sha256: str
    archive_executable: str
    executable: str
    executable_sha256: str
    download_url: str


@dataclass(frozen=True)
class AntigravityCliBinary:
    """A verified executable the runner may start."""

    path: Path
    version: str
    sha256: str


@dataclass(frozen=True)
class AntigravityCliProbe:
    """Result of the zero-consumption availability check."""

    expected_path: Path
    guidance: str
    version: str | None = None
    binary: AntigravityCliBinary | None = None
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.binary is not None


ANTIGRAVITY_CLI_RELEASES = (
    AntigravityCliRelease(
        version="1.2.4",
        platform=WINDOWS_X64,
        archive="agy_cli_windows_x64.zip",
        archive_sha256=(
            "c3151993a59442affc3cc256c53cfded466abf80390cd648e7cbc0241c5a5190"
        ),
        archive_executable="antigravity.exe",
        executable="agy.exe",
        executable_sha256=(
            "05cdf2444b1bc9ee278386756b2cf2afbba94e822f21580278e07e206c3125b8"
        ),
        download_url=(
            "https://github.com/google-antigravity/antigravity-cli/releases/"
            "download/1.2.4/agy_cli_windows_x64.zip"
        ),
    ),
)


def current_platform() -> str:
    if sys.platform != "win32":
        return sys.platform
    machine = platform.machine().lower()
    return WINDOWS_X64 if machine in {"amd64", "x86_64"} else machine


def pinned_release(platform_name: str | None = None) -> AntigravityCliRelease | None:
    name = platform_name or current_platform()
    return next(
        (release for release in ANTIGRAVITY_CLI_RELEASES if release.platform == name),
        None,
    )


def binary_path(runtime_root: Path, release: AntigravityCliRelease) -> Path:
    return (
        Path(runtime_root)
        / RUNTIME_DIRECTORY
        / release.version
        / release.executable
    )


def install_guidance(release: AntigravityCliRelease, path: Path) -> str:
    """Return the one download-and-placement text shared by page and runner."""

    return (
        f"Antigravity CLI {release.version} must be placed at {path}. "
        f"Download {release.archive} from {release.download_url}, extract "
        f"{release.archive_executable} from the archive, rename it to "
        f"{release.executable}, and copy it to that path. agent-shell never "
        "downloads or upgrades the CLI."
    )


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe_antigravity_cli(runtime_root: Path) -> AntigravityCliProbe:
    """Check path and hash without starting the model or spending quota."""

    release = pinned_release()
    if release is None:
        return AntigravityCliProbe(
            expected_path=Path(runtime_root) / RUNTIME_DIRECTORY,
            detail=(
                "No pinned Antigravity CLI release exists for platform "
                f"{current_platform()!r}."
            ),
            guidance=(
                "External Agent currently requires a pinned Windows x64 "
                "Antigravity CLI release."
            ),
        )
    path = binary_path(runtime_root, release)
    guidance = install_guidance(release, path)
    if not path.is_file():
        return AntigravityCliProbe(
            expected_path=path,
            version=release.version,
            detail="The pinned Antigravity CLI executable is missing.",
            guidance=guidance,
        )
    digest = file_sha256(path)
    if digest != release.executable_sha256:
        return AntigravityCliProbe(
            expected_path=path,
            version=release.version,
            detail=(
                f"The executable at {path} is not the pinned Antigravity CLI "
                f"{release.version} build (sha256 {digest})."
            ),
            guidance=guidance,
        )
    return AntigravityCliProbe(
        expected_path=path,
        version=release.version,
        binary=AntigravityCliBinary(
            path=path,
            version=release.version,
            sha256=digest,
        ),
        guidance=guidance,
    )


def resolved_antigravity_cli(runtime_root: Path) -> AntigravityCliBinary:
    probe = probe_antigravity_cli(runtime_root)
    if probe.binary is not None:
        return probe.binary
    raise external_agent_binary_error(probe)


def external_agent_binary_error(probe: AntigravityCliProbe) -> AgentRuntimeError:
    detail = probe.detail or "The Antigravity CLI executable is unavailable."
    return binary_unavailable(f"{detail} {probe.guidance}", path=probe.expected_path)


__all__ = [
    "ANTIGRAVITY_CLI_RELEASES",
    "RUNTIME_DIRECTORY",
    "AntigravityCliBinary",
    "AntigravityCliProbe",
    "AntigravityCliRelease",
    "binary_path",
    "current_platform",
    "external_agent_binary_error",
    "file_sha256",
    "install_guidance",
    "pinned_release",
    "probe_antigravity_cli",
    "resolved_antigravity_cli",
]
