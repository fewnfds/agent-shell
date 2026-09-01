from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.python_packages.packages import (
    PythonPackageAdapter,
    resolve_python_package,
    scan_python_package,
)
from agent_shell.runtime.errors import AgentRuntimeError


EventOutputKind = Literal["agent", "workflow"]
ProtocolEvent = Mapping[str, object]
EventOutputOrigin = Mapping[str, object]
EventOutputCallable = Callable[[ProtocolEvent, EventOutputOrigin], object]
EventSegmentEndCallable = Callable[[ProtocolEvent, EventOutputOrigin], object]
EventRunOutputCallable = Callable[[Mapping[str, object], EventOutputOrigin], object]

_SPECS: dict[EventOutputKind, tuple[PythonPackageAdapter, str]] = {
    "agent": ("agent-event-output", "agent-event-output"),
    "workflow": ("workflow-event-output", "workflow-event-output"),
}
_FAMILY = "event-output"
_ENTRYPOINT = "output"
_PARAMETERS = ("event", "origin")


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
        self._kind = kind
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
        self._segment_ends: dict[str, EventSegmentEndCallable | None] = {}
        self._run_outputs: dict[str, EventRunOutputCallable | None] = {}
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

    def segment_end_for(
        self,
        binding_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> EventSegmentEndCallable | None:
        """Load the optional presentation-segment suffix hook."""

        return self._optional_entrypoint_for(
            self._segment_ends,
            "segment_end",
            binding_id,
            package_owner_id,
            reference,
        )

    def workflow_run_output_for(
        self,
        binding_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> EventRunOutputCallable | None:
        """Load the optional Shell-owned run-status hook from an output package.

        ``output`` remains the sole protocol-event entrypoint.  ``run_output``
        is intentionally separate because synthetic lifecycle status is a
        product event, not a LangGraph ProtocolEvent.
        """
        if self._kind != "workflow":
            raise RuntimeError("run_output belongs to Workflow Event Output")
        return self._optional_entrypoint_for(
            self._run_outputs,
            "run_output",
            binding_id,
            package_owner_id,
            reference,
        )

    def _optional_entrypoint_for(
        self,
        cache: dict[str, Callable[[Mapping[str, object], EventOutputOrigin], object] | None],
        name: str,
        binding_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> Callable[[Mapping[str, object], EventOutputOrigin], object] | None:
        if binding_id in cache:
            return cache[binding_id]
        module, _metadata, _package_dir = self._loader.load(
            binding_id,
            self._binding_kind,
            0,
            str(reference["folder"]),
            package_owner_id=package_owner_id,
        )
        function = getattr(module, name, None)
        if function is None:
            cache[binding_id] = None
            return None

        if not callable(function) or inspect.iscoroutinefunction(function):
            raise AgentRuntimeError(
                "python_package.entrypoint_invalid",
                f"The event output package has an invalid {name} entrypoint.",
                status_code=422,
            )
        signature = inspect.signature(function)
        parameters = tuple(signature.parameters.values())
        if (
            tuple(parameter.name for parameter in parameters) != ("event", "origin")
            or any(
                parameter.kind
                in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
                or parameter.default is not inspect.Parameter.empty
                for parameter in parameters
            )
        ):
            raise AgentRuntimeError(
                "python_package.entrypoint_invalid",
                f"The {name} entrypoint must accept exactly event and origin.",
                status_code=422,
            )
        cache[binding_id] = function
        return function

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()
        self._outputs.clear()
        self._segment_ends.clear()
        self._run_outputs.clear()


__all__ = [
    "EventOutputCallable",
    "EventOutputOrigin",
    "EventSegmentEndCallable",
    "EventRunOutputCallable",
    "EventOutputPackageRuntime",
    "resolve_agent_event_output_package",
    "resolve_workflow_event_output_package",
    "scan_agent_event_output_package",
    "scan_workflow_event_output_package",
]
