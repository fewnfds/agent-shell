from __future__ import annotations

from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.model_connections import ModelResourceStore


class ConfigurationRepositoryManagementService:
    """Own repository-wide commands that also update instance model bindings."""

    def __init__(
        self,
        repository: FileConfigRepository,
        model_resources: ModelResourceStore,
    ) -> None:
        self._repository = repository
        self._model_resources = model_resources

    def copy(self, source_id: str, name: str) -> dict[str, object]:
        with self._repository.exclusive_config_mutation():
            copied, target_ids = self._repository.copy_repository(source_id, name)
            target_id = str(copied["id"])
            try:
                self._model_resources.copy_repository_bindings(
                    source_id,
                    target_id,
                    target_ids,
                )
            except BaseException:
                self._repository.delete_repository(target_id)
                raise
            return copied

    def delete(self, repository_id: str) -> dict[str, object]:
        with self._repository.exclusive_config_mutation():
            bindings = self._model_resources.remove_repository_bindings(
                repository_id
            )
            try:
                return self._repository.delete_repository(repository_id)
            except BaseException:
                self._model_resources.restore_repository_bindings(
                    repository_id,
                    bindings,
                )
                raise

    def export(self, repository_id: str) -> tuple[bytes, str]:
        return self._repository.export_repository(repository_id)


__all__ = ["ConfigurationRepositoryManagementService"]
