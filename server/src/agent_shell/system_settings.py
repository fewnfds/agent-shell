from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import SecretStr, ValidationError

from agent_shell.langsmith_tracing import (
    LangSmithConnectionError,
    validate_langsmith_connection,
)
from agent_shell.settings import Settings, SettingsError
from agent_shell.security import ApiKeyPolicyError, validate_api_key_policy
from agent_shell.storage.file_config import FileConfigRepository
from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    InstanceEnvironmentStore,
    SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
)


class SystemSettingsError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message_key: str,
        fallback: str,
        message_args: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message_key = message_key
        self.message_args = message_args or {}
        super().__init__(fallback)


def _secret_value(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def _validation_keys(error: ValidationError) -> tuple[str, ...]:
    keys = {
        f"AGENT_SHELL_{str(item['loc'][0]).upper()}"
        for item in error.errors(include_input=False, include_url=False)
        if item.get("loc")
    }
    return tuple(sorted(keys))


class SystemSettingsService:
    def __init__(
        self,
        active: Settings,
        api_key_provider: Callable[[], str | None],
        configuration: FileConfigRepository,
        environment: InstanceEnvironmentStore,
        mutations: ConfigurationMutationCoordinator,
    ) -> None:
        self._active = active
        self._saved = active
        self._api_key_provider = api_key_provider
        self._configuration = configuration
        self._environment = environment
        self._mutations = mutations

    @staticmethod
    def _public(settings: Settings) -> dict[str, Any]:
        return {
            "host": settings.host,
            "port": settings.port,
            "n_jobs_per_worker": settings.n_jobs_per_worker,
            "recursion_limit": settings.recursion_limit,
            "max_concurrency": settings.max_concurrency,
            "debug_port": settings.debug_port,
            "allow_remote": settings.allow_remote,
            "langsmith_tracing_enabled": settings.langsmith_tracing_enabled,
            "langsmith_endpoint": settings.langsmith_endpoint,
            "langsmith_project": settings.langsmith_project,
            "langsmith_workspace_id": settings.langsmith_workspace_id,
            "langsmith_api_key": {
                "configured": settings.langsmith_api_key is not None,
            },
            "cors_origins": list(settings.cors_origins),
            "trusted_proxy_cidrs": list(settings.trusted_proxy_cidrs),
            "management_token": {
                "configured": settings.management_token is not None,
            },
        }

    @staticmethod
    def _same(left: Settings, right: Settings) -> bool:
        return (
            SystemSettingsService._public(left)
            == SystemSettingsService._public(right)
            and _secret_value(left.management_token)
            == _secret_value(right.management_token)
            and _secret_value(left.langsmith_api_key)
            == _secret_value(right.langsmith_api_key)
        )

    def get(self) -> dict[str, Any]:
        return {
            **self._public(self._saved),
            "restart_required": not self._same(self._active, self._saved),
        }

    @staticmethod
    def _apply_management_password(
        current: SecretStr | None,
        payload: dict[str, Any],
    ) -> str | None:
        operation = payload.get("operation")
        if operation == "preserve":
            return _secret_value(current)
        if operation == "replace":
            value = payload.get("value")
            if isinstance(value, str) and value:
                return value
        raise SystemSettingsError(
            422,
            "system_secret_operation_invalid",
            "errors.systemSecretOperationInvalid",
            "The secret update operation is invalid.",
        )

    def _candidate(self, payload: dict[str, Any]) -> Settings:
        langsmith_api_key = self._apply_optional_secret(
            self._saved.langsmith_api_key,
            payload["langsmith_api_key"],
        )
        values = {
            "host": payload["host"],
            "port": payload["port"],
            "n_jobs_per_worker": payload["n_jobs_per_worker"],
            "recursion_limit": payload["recursion_limit"],
            "max_concurrency": payload["max_concurrency"],
            "debug_port": payload["debug_port"],
            "allow_remote": payload["allow_remote"],
            "langsmith_tracing_enabled": payload["langsmith_tracing_enabled"],
            "langsmith_endpoint": payload["langsmith_endpoint"],
            "langsmith_project": payload["langsmith_project"],
            "langsmith_workspace_id": payload["langsmith_workspace_id"],
            "langsmith_api_key": langsmith_api_key,
            "management_token": self._apply_management_password(
                self._saved.management_token,
                payload["management_token"],
            ),
            "cors_origins": payload["cors_origins"],
            "trusted_proxy_cidrs": payload["trusted_proxy_cidrs"],
        }
        try:
            candidate = Settings(**values)
        except ValidationError as exc:
            keys = ", ".join(_validation_keys(exc))
            raise SystemSettingsError(
                422,
                "system_settings_invalid",
                "errors.systemSettingsInvalid",
                "The system settings are invalid.",
                {"keys": keys},
            ) from None
        candidate.bind_paths(self._active.application_home, self._active.data_root)
        try:
            candidate.validate_deployment()
        except SettingsError as exc:
            raise SystemSettingsError(
                422,
                "system_settings_invalid",
                "errors.systemSettingsInvalid",
                "The system settings are invalid.",
                {"keys": ", ".join(exc.keys)},
            ) from None
        try:
            validate_api_key_policy(candidate, self._api_key_provider())
        except ApiKeyPolicyError as exc:
            raise SystemSettingsError(
                422,
                exc.code,
                exc.message_key,
                exc.safe_message,
            ) from None
        return candidate

    @staticmethod
    def _apply_optional_secret(
        current: SecretStr | None,
        payload: dict[str, Any],
    ) -> str | None:
        operation = payload.get("operation")
        if operation == "keep":
            return _secret_value(current)
        if operation == "clear":
            return None
        if operation == "replace":
            value = payload.get("value")
            if isinstance(value, str) and value:
                return value
        raise SystemSettingsError(
            422,
            "system_secret_operation_invalid",
            "errors.systemSecretOperationInvalid",
            "The secret update operation is invalid.",
        )

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate = self._candidate(payload)
        langsmith_connection_changed = (
            not self._saved.langsmith_tracing_enabled
            or candidate.langsmith_endpoint != self._saved.langsmith_endpoint
            or candidate.langsmith_workspace_id != self._saved.langsmith_workspace_id
            or _secret_value(candidate.langsmith_api_key)
            != _secret_value(self._saved.langsmith_api_key)
        )
        if candidate.langsmith_tracing_enabled and langsmith_connection_changed:
            try:
                validate_langsmith_connection(candidate)
            except LangSmithConnectionError:
                raise SystemSettingsError(
                    422,
                    "langsmith_connection_failed",
                    "errors.langsmithConnectionFailed",
                    "LangSmith connection validation failed. Check the API key, endpoint region, and workspace ID.",
                ) from None
        try:
            def mutate(system: dict[str, Any]) -> None:
                system["settings"] = {
                    "host": candidate.host,
                    "port": candidate.port,
                    "n_jobs_per_worker": candidate.n_jobs_per_worker,
                    "recursion_limit": candidate.recursion_limit,
                    "max_concurrency": candidate.max_concurrency,
                    "debug_port": candidate.debug_port,
                    "allow_remote": candidate.allow_remote,
                    "langsmith_tracing_enabled": candidate.langsmith_tracing_enabled,
                    "langsmith_endpoint": candidate.langsmith_endpoint,
                    "langsmith_project": candidate.langsmith_project,
                    "langsmith_workspace_id": candidate.langsmith_workspace_id,
                    "cors_origins": list(candidate.cors_origins),
                    "trusted_proxy_cidrs": list(candidate.trusted_proxy_cidrs),
                }
            set_values: dict[str, str] = {}
            remove_keys: set[str] = set()
            if payload["management_token"]["operation"] == "replace":
                management_token = _secret_value(candidate.management_token)
                assert management_token is not None
                set_values["AGENT_SHELL_MANAGEMENT_TOKEN"] = management_token
            operation = payload["langsmith_api_key"]["operation"]
            if operation == "replace":
                langsmith_api_key = _secret_value(candidate.langsmith_api_key)
                assert langsmith_api_key is not None
                set_values["LANGSMITH_API_KEY"] = langsmith_api_key
            elif operation == "clear":
                remove_keys.add("LANGSMITH_API_KEY")

            with self._mutations.mutation():
                original_environment = self._environment.owned_values(
                    SYSTEM_SETTINGS_ENVIRONMENT_OWNER
                )
                try:
                    if set_values or remove_keys:
                        self._environment.patch(
                            SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
                            set_values=set_values,
                            remove_keys=remove_keys,
                        )
                    self._configuration.update_system(mutate)
                except BaseException:
                    try:
                        self._environment.replace_owned(
                            SYSTEM_SETTINGS_ENVIRONMENT_OWNER,
                            original_environment,
                        )
                    except BaseException:
                        pass
                    raise
        except OSError as exc:
            raise SystemSettingsError(
                500,
                "system_settings_write_failed",
                "errors.systemSettingsWriteFailed",
                "The system settings could not be saved.",
            ) from exc
        self._saved = candidate
        return self.get()
