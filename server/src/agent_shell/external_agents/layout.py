"""Filesystem layout one External Agent owns inside the instance data root.

``data/antigravity/<external_agent_id>/`` is the disk owner. Its
``lifecycles/<lifecycle_id>/`` child holds everything one Lifecycle needs:
an isolated CLI HOME, the Lifecycle workspace, and one evidence directory per
run. HOME and session evidence belong to the Lifecycle; the workspace holds
user output and survives Lifecycle deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from uuid import uuid4

from agent_shell.configuration.identity import is_configuration_id


AGENT_DIRECTORY = "antigravity"
LIFECYCLE_DIRECTORY = "lifecycles"


def _identity(value: object, *, label: str) -> str:
    if not is_configuration_id(value):
        raise ValueError(f"{label} must be a canonical lowercase UUID4 id")
    return str(value)


def new_session_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class AntigravitySessionLayout:
    """Evidence written for one CLI process."""

    root: Path

    @property
    def meta_file(self) -> Path:
        return self.root / "meta.json"

    @property
    def event_log(self) -> Path:
        return self.root / "events.ndjson"

    @property
    def stderr_log(self) -> Path:
        return self.root / "stderr.log"

    @property
    def result_file(self) -> Path:
        return self.root / "result.json"

    def create(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AntigravityLifecycleLayout:
    """Isolated HOME, workspace, and run evidence for one Lifecycle."""

    root: Path

    @property
    def home(self) -> Path:
        return self.root / "home"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def sessions(self) -> Path:
        return self.root / "sessions"

    @property
    def run_lock(self) -> Path:
        return self.root / ".run.lock"

    def session(self, session_id: str) -> AntigravitySessionLayout:
        return AntigravitySessionLayout(
            self.sessions / _identity(session_id, label="session id")
        )

    def create(self) -> None:
        for directory in (self.home, self.workspace, self.sessions):
            directory.mkdir(parents=True, exist_ok=True)

    def remove_state(self) -> None:
        """Delete the Lifecycle-owned state, keeping the workspace."""

        root = self.root.resolve()
        for directory in (self.home, self.sessions):
            target = directory.resolve()
            if target.parent != root:
                raise ValueError(
                    f"Refusing to delete {target} outside {root}"
                )
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        lock = self.run_lock.resolve()
        if lock.parent == root and lock.exists():
            lock.unlink()


def antigravity_agent_root(data_root: Path, external_agent_id: str) -> Path:
    """Return the directory a preset owns, keyed by its configuration UUID."""

    return (
        Path(data_root)
        / AGENT_DIRECTORY
        / _identity(external_agent_id, label="external agent id")
    )


def antigravity_lifecycle_layout(
    data_root: Path,
    external_agent_id: str,
    lifecycle_id: str,
) -> AntigravityLifecycleLayout:
    return AntigravityLifecycleLayout(
        antigravity_agent_root(data_root, external_agent_id)
        / LIFECYCLE_DIRECTORY
        / _identity(lifecycle_id, label="lifecycle id")
    )


__all__ = [
    "AGENT_DIRECTORY",
    "AntigravityLifecycleLayout",
    "AntigravitySessionLayout",
    "antigravity_agent_root",
    "antigravity_lifecycle_layout",
    "new_session_id",
]
