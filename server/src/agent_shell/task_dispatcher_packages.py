from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.python_packages.packages import (
    resolve_python_package,
    scan_python_package,
)
from agent_shell.runtime.errors import AgentRuntimeError


_FAMILY = "workflow-node"
_ADAPTER = "task-dispatcher"
_FACTORY = "create_dispatcher"
_PARAMETERS: tuple[str, ...] = ()


def scan_task_dispatcher_package(
    folder: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    return scan_python_package(
        folder,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=_ADAPTER,
        factory_name=_FACTORY,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


def resolve_task_dispatcher_package(
    folder: str,
    directory: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    return resolve_python_package(
        folder,
        directory,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=_ADAPTER,
        factory_name=_FACTORY,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


class TaskDispatcherPackageRuntime:
    def __init__(
        self,
        *,
        request_id: str,
        packages_dir: Path,
        runtime_root: Path,
    ) -> None:
        self._loader = PythonPackageLoader(
            request_id=request_id,
            packages_dir=packages_dir,
            runtime_root=runtime_root,
            family=_FAMILY,
            adapter=_ADAPTER,
            factory_name=_FACTORY,
            factory_parameters=_PARAMETERS,
        )
        self._dispatchers: dict[str, Callable[..., Any]] = {}
        self._closed = False

    def dispatcher_for(
        self,
        owner_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> Callable[..., Any]:
        cached = self._dispatchers.get(owner_id)
        if cached is not None:
            return cached
        folder = str(reference["folder"])
        factory, _metadata, _package_dir = self._loader.entrypoint(
            owner_id,
            "task-dispatcher",
            0,
            folder,
            package_owner_id=package_owner_id,
        )
        try:
            dispatch = factory()
        except Exception as exc:
            raise AgentRuntimeError(
                "task_dispatcher_package.materialization_failed",
                f"Task Dispatcher package {folder!r} could not create a dispatcher.",
                status_code=422,
            ) from exc
        if not callable(dispatch) or not inspect.iscoroutinefunction(dispatch):
            raise AgentRuntimeError(
                "task_dispatcher_package.result_invalid",
                f"Task Dispatcher package {folder!r} must return an async dispatch callable.",
                status_code=422,
            )
        try:
            signature = inspect.signature(dispatch)
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeError(
                "task_dispatcher_package.result_invalid",
                f"Task Dispatcher package {folder!r} returned an invalid dispatch callable.",
                status_code=422,
            ) from exc
        parameters = list(signature.parameters.values())
        if (
            [parameter.name for parameter in parameters] != ["state", "runtime"]
            or any(
                parameter.kind is not parameter.POSITIONAL_OR_KEYWORD
                or parameter.default is not parameter.empty
                for parameter in parameters
            )
        ):
            raise AgentRuntimeError(
                "task_dispatcher_package.result_invalid",
                f"Task Dispatcher package {folder!r} dispatch must accept exactly state and runtime.",
                status_code=422,
            )
        self._dispatchers[owner_id] = dispatch
        return dispatch

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()
        self._dispatchers.clear()


__all__ = [
    "TaskDispatcherPackageRuntime",
    "resolve_task_dispatcher_package",
    "scan_task_dispatcher_package",
]
