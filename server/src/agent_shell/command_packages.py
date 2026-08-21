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
_ADAPTER = "command"
_FACTORY = "create_command"
_PARAMETERS: tuple[str, ...] = ()


def scan_command_package(
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


def resolve_command_package(
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

class CommandPackageRuntime:
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
        self._commands: dict[str, Callable[..., Any]] = {}
        self._closed = False

    def command_for(
        self,
        owner_id: str,
        package_owner_id: str,
        reference: dict[str, Any],
    ) -> Callable[..., Any]:
        cached = self._commands.get(owner_id)
        if cached is not None:
            return cached
        folder = str(reference["folder"])
        factory, metadata, _package_dir = self._loader.entrypoint(
            owner_id,
            "command",
            0,
            folder,
            package_owner_id=package_owner_id,
        )
        try:
            command = factory()
        except Exception as exc:
            raise AgentRuntimeError(
                "command_package.materialization_failed",
                f"Command package {folder!r} could not create a command.",
                status_code=422,
            ) from exc
        if not callable(command) or not inspect.iscoroutinefunction(command):
            raise AgentRuntimeError(
                "command_package.result_invalid",
                f"Command package {folder!r} must return an async command callable.",
                status_code=422,
            )
        try:
            signature = inspect.signature(command)
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeError(
                "command_package.result_invalid",
                f"Command package {folder!r} returned an invalid command callable.",
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
                "command_package.result_invalid",
                f"Command package {folder!r} command must accept exactly state and runtime.",
                status_code=422,
            )
        self._commands[owner_id] = command
        return command

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()
        self._commands.clear()


__all__ = [
    "CommandPackageRuntime",
    "resolve_command_package",
    "scan_command_package",
]
