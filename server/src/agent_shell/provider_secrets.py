from __future__ import annotations

from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.model_connections import (
    ModelCredentialReferenceMissingError,
    ModelResourceSnapshot,
    ModelResourceStore,
)


class ProviderCredentialError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.safe_message = message
        super().__init__(code)


class ProviderSecretResolver:
    """Runtime-facing resolver for model connection credentials."""

    def __init__(
        self,
        repository: FileConfigRepository,
        model_connections: ModelResourceStore | ModelResourceSnapshot | None = None,
    ) -> None:
        self._repository = repository
        self._connections = model_connections or ModelResourceStore(repository.data_root)

    @property
    def model_connections(self) -> ModelResourceStore | ModelResourceSnapshot:
        return self._connections

    @property
    def repository_id(self) -> str:
        return self._repository.repository_id

    def _stored_model(self, block_id: str) -> dict:
        try:
            return self._connections.resolve_connection(block_id)
        except ModelCredentialReferenceMissingError as exc:
            raise ProviderCredentialError(
                "provider_secret_reference_missing",
                "The model credential reference is missing.",
            ) from exc
        except KeyError as exc:
            raise ProviderCredentialError(
                "model_connection_not_found",
                "The model connection does not exist.",
            ) from exc

    def resolve_model(self, block_id: str) -> str | None:
        payload = self._stored_model(block_id)
        credential = payload.get("credential")
        if credential is None:
            return None
        if not isinstance(credential, str):
            raise ProviderCredentialError("provider_credential_invalid", "The model credential metadata is invalid.")
        if not credential:
            raise ProviderCredentialError("provider_secret_reference_missing", "The model credential reference is missing.")
        return credential

    def resolve_request(
        self,
        credential: str | None,
        *,
        provider: str,
        block_id: str = "",
        base_url: str = "",
    ) -> str | None:
        if credential is not None:
            return credential
        if not block_id:
            return None
        payload = self._stored_model(block_id)
        if payload.get("provider") != provider or str(payload.get("base_url", "")).rstrip("/") != base_url.rstrip("/"):
            raise ProviderCredentialError(
                "provider_credential_connection_changed",
                "A saved credential cannot be reused for a different model connection.",
            )
        return self.resolve_model(block_id)
