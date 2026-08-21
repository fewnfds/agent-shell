from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable
from uuid import uuid4

from agent_shell.python_packages.packages import (
    PythonPackageAdapter,
    PythonPackageFamily,
    resolve_python_package,
)
from agent_shell.registries.errors import ResourceScanError
from agent_shell.runtime.errors import AgentRuntimeError


class PythonPackageLoader:
    def __init__(
        self,
        *,
        request_id: str,
        packages_dir: Path,
        runtime_root: Path,
        family: PythonPackageFamily,
        adapter: PythonPackageAdapter,
        factory_name: str,
        factory_parameters: tuple[str, ...] | None,
    ) -> None:
        self._request_id = request_id
        self._packages_dir = packages_dir
        self._runtime_root = runtime_root
        self._family = family
        self._adapter = adapter
        self._factory_name = factory_name
        self._factory_parameters = factory_parameters
        self._module_namespace = (
            f"_agent_shell_python_package_{uuid4().hex}"
        )
        self._modules: dict[
            tuple[str, str, int], tuple[ModuleType, dict[str, object], Path]
        ] = {}
        self._module_names: set[str] = set()

    def load(
        self,
        owner_id: str,
        binding_kind: str,
        binding_index: int,
        folder: str,
        *,
        package_owner_id: str,
    ) -> tuple[ModuleType, dict[str, object], Path]:
        key = (owner_id, binding_kind, binding_index)
        cached = self._modules.get(key)
        if cached is not None:
            return cached
        try:
            resolved = resolve_python_package(
                folder,
                self._packages_dir,
                owner_id=package_owner_id,
                family=self._family,
                adapter=self._adapter,
                factory_name=self._factory_name,
                factory_parameters=self._factory_parameters,
                runtime_root=self._runtime_root,
            )
        except ResourceScanError as exc:
            raise AgentRuntimeError(
                "python_package.invalid",
                f"Python package {folder!r} is invalid.",
                status_code=422,
            ) from exc
        if resolved is None:
            raise AgentRuntimeError(
                "python_package.not_found",
                f"Python package {folder!r} does not exist.",
                status_code=422,
            )
        metadata, package_dir = resolved
        if metadata["dependency_status"] != "ready":
            raise AgentRuntimeError(
                "python_package.dependencies_not_ready",
                f"Python package {folder!r} dependencies are not ready.",
                status_code=409,
            )
        module_name = f"{self._module_namespace}_{len(self._modules)}"
        spec = importlib.util.spec_from_file_location(
            module_name,
            package_dir / "main.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise AgentRuntimeError(
                "python_package.load_failed",
                f"Python package {folder!r} could not be loaded.",
                status_code=422,
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            self._remove_module(module_name)
            raise AgentRuntimeError(
                "python_package.load_failed",
                f"Python package {folder!r} could not be loaded.",
                status_code=422,
            ) from exc
        value = (module, metadata, package_dir)
        self._modules[key] = value
        self._module_names.add(module_name)
        return value

    def entrypoint(
        self,
        owner_id: str,
        binding_kind: str,
        binding_index: int,
        folder: str,
        *,
        package_owner_id: str,
    ) -> tuple[Callable[..., Any], dict[str, object], Path]:
        module, metadata, package_dir = self.load(
            owner_id,
            binding_kind,
            binding_index,
            folder,
            package_owner_id=package_owner_id,
        )
        function = getattr(module, self._factory_name, None)
        if not callable(function) or inspect.iscoroutinefunction(function):
            raise AgentRuntimeError(
                "python_package.entrypoint_invalid",
                f"Python package {folder!r} has an invalid {self._factory_name} entrypoint.",
                status_code=422,
            )
        return function, metadata, package_dir

    @staticmethod
    def _remove_module(module_name: str) -> None:
        for loaded_name in tuple(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(f"{module_name}."):
                sys.modules.pop(loaded_name, None)

    def close(self) -> None:
        for module_name in self._module_names:
            self._remove_module(module_name)
        self._modules.clear()
        self._module_names.clear()


__all__ = ["PythonPackageLoader"]
