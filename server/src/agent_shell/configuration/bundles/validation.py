from __future__ import annotations

from pathlib import Path

from agent_shell.storage.agent_configs import AgentConfigStore
from agent_shell.storage.blocks import BlockStore
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.validation.models import ValidationReport
from agent_shell.validation.repository import RepositoryValidationService
from agent_shell.validation.service import ConfigurationValidationService
from agent_shell.python_packages.validation import PythonPackageValidationService


def validate_bundle_snapshot(
    config: dict,
    *,
    data_root: Path,
    packages_dir: Path,
    runtime_root: Path,
) -> ValidationReport:
    repository = FileConfigRepository.from_snapshot(data_root, config)
    blocks = BlockStore(repository)
    agent_configs = AgentConfigStore(repository)
    package_validation = PythonPackageValidationService(
        packages_dir=packages_dir,
        runtime_root=runtime_root,
    )
    validation = ConfigurationValidationService(
        blocks,
        agent_configs,
        package_validation,
    )
    return RepositoryValidationService(
        repository,
        blocks,
        validation,
    ).validate_repository()


__all__ = ["validate_bundle_snapshot"]
