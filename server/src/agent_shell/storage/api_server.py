from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from agent_shell.security_events import SecurityEventLogger, emit_configuration_events

if TYPE_CHECKING:
    from agent_shell.storage.database import SQLiteDatabase
    from agent_shell.storage.file_config import FileConfigRepository

from agent_shell.storage.configuration_mutations import ConfigurationMutationCoordinator
from agent_shell.storage.environment import (
    API_SERVER_ENVIRONMENT_OWNER,
    InstanceEnvironmentStore,
)


ApiKeyOperation = Literal["keep", "replace", "clear"]
class ApiServerStore:
    def __init__(
        self,
        database: SQLiteDatabase,
        config_repository: FileConfigRepository,
        environment: InstanceEnvironmentStore | None = None,
        mutations: ConfigurationMutationCoordinator | None = None,
        event_logger: SecurityEventLogger | None = None,
    ) -> None:
        self._database = database
        self._config_repository = config_repository
        self._mutations = mutations or ConfigurationMutationCoordinator()
        self._environment = environment or InstanceEnvironmentStore(
            config_repository.data_root / "config" / "agent-shell.env",
            mutations=self._mutations,
        )
        self._events = event_logger
    def settings(self) -> dict[str, object]:
        values = self._config_repository.system().get("api_server", {})
        return {
            "enabled": bool(values.get("enabled", True)),
            "api_key_configured": self.api_key() is not None,
            "message_interception_enabled": bool(
                values.get("message_interception_enabled", False)
            ),
        }

    def api_key(self) -> str | None:
        return self._environment.get("AGENT_SHELL_API_KEY")

    def is_enabled(self) -> bool:
        return bool(self._config_repository.system().get("api_server", {}).get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        self._config_repository.update_system(lambda system: system.setdefault("api_server", {}).__setitem__("enabled", bool(enabled)))
        self._emit_updated(state="running" if enabled else "stopped")

    def set_message_interception_enabled(self, enabled: bool) -> None:
        self._config_repository.update_system(
            lambda system: system.setdefault("api_server", {}).__setitem__(
                "message_interception_enabled", bool(enabled)
            )
        )
        self._emit_updated(
            state="intercepting" if enabled else "passing-through"
        )

    def update_settings(
        self,
        *,
        api_key_operation: ApiKeyOperation,
        api_key: str | None,
    ) -> None:
        with self._mutations.mutation():
            original_environment = self._environment.owned_values(
                API_SERVER_ENVIRONMENT_OWNER
            )
            try:
                if api_key_operation == "replace" and api_key is not None:
                    self._environment.patch(
                        API_SERVER_ENVIRONMENT_OWNER,
                        set_values={"AGENT_SHELL_API_KEY": api_key},
                    )
                elif api_key_operation == "clear":
                    self._environment.patch(
                        API_SERVER_ENVIRONMENT_OWNER,
                        remove_keys={"AGENT_SHELL_API_KEY"},
                    )
            except BaseException:
                try:
                    self._environment.replace_owned(
                        API_SERVER_ENVIRONMENT_OWNER,
                        original_environment,
                    )
                except BaseException:
                    pass
                raise
        self._emit_updated()

    def _emit_updated(self, *, state: str = "") -> None:
        emit_configuration_events(
            self._events,
            action="updated",
            entity="api-server",
            entity_id="singleton",
            state=state,
        )
