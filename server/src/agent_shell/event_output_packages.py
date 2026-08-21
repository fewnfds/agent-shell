from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.python_packages.packages import (
    PythonPackageAdapter,
    resolve_python_package,
    scan_python_package,
)


EventOutputKind = Literal["agent", "workflow"]
EventOutputCallable = Callable[[dict[str, object]], object]

_SPECS: dict[EventOutputKind, tuple[PythonPackageAdapter, str]] = {
    "agent": ("agent-event-output", "agent-event-output"),
    "workflow": ("workflow-event-output", "workflow-event-output"),
}
_FAMILY = "event-output"
_ENTRYPOINT = "output"
_PARAMETERS = ("event",)


def _scan(
    kind: EventOutputKind,
    folder: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    adapter, _binding_kind = _SPECS[kind]
    return scan_python_package(
        folder,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=adapter,
        factory_name=_ENTRYPOINT,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


def _resolve(
    kind: EventOutputKind,
    folder: str,
    directory: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    adapter, _binding_kind = _SPECS[kind]
    return resolve_python_package(
        folder,
        directory,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=adapter,
        factory_name=_ENTRYPOINT,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


def scan_agent_event_output_package(
    folder: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    return _scan("agent", folder, owner_id=owner_id, runtime_root=runtime_root)


def resolve_agent_event_output_package(
    folder: str,
    directory: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    return _resolve(
        "agent",
        folder,
        directory,
        owner_id=owner_id,
        runtime_root=runtime_root,
    )


def scan_workflow_event_output_package(
    folder: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    return _scan("workflow", folder, owner_id=owner_id, runtime_root=runtime_root)


def resolve_workflow_event_output_package(
    folder: str,
    directory: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    return _resolve(
        "workflow",
        folder,
        directory,
        owner_id=owner_id,
        runtime_root=runtime_root,
    )


class EventOutputPackageRuntime:
    def __init__(
        self,
        kind: EventOutputKind,
        *,
        request_id: str,
        packages_dir: Path,
        runtime_root: Path,
    ) -> None:
        adapter, self._binding_kind = _SPECS[kind]
        self._loader = PythonPackageLoader(
            request_id=request_id,
            packages_dir=packages_dir,
            runtime_root=runtime_root,
            family=_FAMILY,
            adapter=adapter,
            factory_name=_ENTRYPOINT,
            factory_parameters=_PARAMETERS,
        )
        self._outputs: dict[str, EventOutputCallable] = {}
        self._closed = False

    def output_for(
        self,
        binding_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> EventOutputCallable:
        cached = self._outputs.get(binding_id)
        if cached is not None:
            return cached
        output, _metadata, _package_dir = self._loader.entrypoint(
            binding_id,
            self._binding_kind,
            0,
            str(reference["folder"]),
            package_owner_id=package_owner_id,
        )
        self._outputs[binding_id] = output
        return output

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()
        self._outputs.clear()


__all__ = [
    "EventOutputCallable",
    "EventOutputPackageRuntime",
    "resolve_agent_event_output_package",
    "resolve_workflow_event_output_package",
    "scan_agent_event_output_package",
    "scan_workflow_event_output_package",
]
