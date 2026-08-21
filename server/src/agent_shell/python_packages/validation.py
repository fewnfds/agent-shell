from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_shell.command_packages import resolve_command_package
from agent_shell.event_output_packages import (
    resolve_agent_event_output_package,
    resolve_workflow_event_output_package,
)
from agent_shell.middleware_packages.packages import resolve_middleware_package
from agent_shell.task_dispatcher_packages import resolve_task_dispatcher_package
from agent_shell.tool_packages import resolve_tool_package
from agent_shell.registries.errors import ResourceScanError
from agent_shell.validation.models import ValidationIssue


PackageResolver = Callable[..., tuple[dict[str, object], Path] | None]


class PythonPackageValidationService:
    def __init__(self, *, packages_dir: Path | Callable[[], Path], runtime_root: Path) -> None:
        self._packages_dir_source = packages_dir
        self._runtime_root = runtime_root

    @property
    def _packages_dir(self) -> Path:
        value = self._packages_dir_source() if callable(self._packages_dir_source) else self._packages_dir_source
        return Path(value).resolve()

    def middleware_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_middleware_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def tool_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_tool_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def agent_event_output_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_agent_event_output_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def workflow_event_output_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_workflow_event_output_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def command_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_command_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def task_dispatcher_issues(
        self,
        reference: dict[str, Any],
        *,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool = True,
    ) -> list[ValidationIssue]:
        return self._reference_issues(
            reference,
            resolver=resolve_task_dispatcher_package,
            scope=scope,
            owner_id=owner_id,
            package_owner_id=package_owner_id,
            owner_name=owner_name,
            path_prefix=path_prefix,
            check_dependencies=check_dependencies,
        )

    def _reference_issues(
        self,
        reference: dict[str, Any],
        *,
        resolver: PackageResolver,
        scope: str,
        owner_id: str,
        package_owner_id: str,
        owner_name: str,
        path_prefix: str,
        check_dependencies: bool,
    ) -> list[ValidationIssue]:
        folder = str(reference.get("folder", ""))
        path = f"{path_prefix}.folder"
        try:
            resolved = resolver(
                folder,
                self._packages_dir,
                owner_id=package_owner_id,
                runtime_root=self._runtime_root,
            )
        except ResourceScanError:
            return [
                self._issue(
                    "python_package.invalid",
                    scope,
                    owner_id,
                    owner_name,
                    path,
                    folder,
                    "The referenced Python package is invalid.",
                    "invalid",
                )
            ]
        if resolved is None:
            return [
                self._issue(
                    "python_package.not_found",
                    scope,
                    owner_id,
                    owner_name,
                    path,
                    folder,
                    "The referenced Python package does not exist.",
                    "notFound",
                )
            ]
        metadata, _folder = resolved
        if not check_dependencies:
            return []
        dependency_status = str(metadata["dependency_status"])
        if dependency_status == "ready":
            return []
        if dependency_status == "failed":
            code = "python_package.dependencies_failed"
            key = "dependenciesFailed"
            message = "The Python package dependencies could not be prepared."
        else:
            code = "python_package.dependencies_restart_required"
            key = "dependenciesRestartRequired"
            message = "Restart Agent Shell to prepare the Python package dependencies."
        return [
            self._issue(
                code,
                scope,
                owner_id,
                owner_name,
                path,
                str(metadata["id"]),
                message,
                key,
            )
        ]

    @staticmethod
    def _issue(
        code: str,
        scope: str,
        owner_id: str,
        owner_name: str,
        path: str,
        package_id: str,
        message: str,
        message_key: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            scope=scope,
            owner_id=owner_id,
            owner_name=owner_name,
            path=path,
            message=message,
            message_key=f"validation.issue.pythonPackage.{message_key}",
            message_args={"package_id": package_id},
        )


__all__ = ["PythonPackageValidationService"]
