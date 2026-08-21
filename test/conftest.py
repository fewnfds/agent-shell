from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGE_ROOT = (PROJECT_ROOT / "server" / "src" / "agent_shell").resolve()


def pytest_sessionstart(session) -> None:
    del session
    spec = find_spec("agent_shell")
    origin = Path(spec.origin).resolve().parent if spec and spec.origin else None
    if origin != EXPECTED_PACKAGE_ROOT:
        raise RuntimeError(
            "Tests resolved agent_shell from the wrong source tree: "
            f"{origin or '<not found>'}. Expected {EXPECTED_PACKAGE_ROOT}. "
            "Use server/.venv/Scripts/python.exe and remove stale editable installs."
        )
