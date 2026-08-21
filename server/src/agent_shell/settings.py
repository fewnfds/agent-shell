from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import yaml
from pydantic import Field, PrivateAttr, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from agent_shell.configuration.repositories import ensure_active_configuration_repository
from agent_shell.storage.environment import (
    EnvironmentFormatError,
    read_environment_file,
    unknown_environment_names,
)


ENV_PREFIX = "AGENT_SHELL_"
DEFAULT_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"


def bearer_token_is_valid(value: str) -> bool:
    return (
        bool(value)
        and value.isascii()
        and all(33 <= ord(character) <= 126 for character in value)
    )


class SettingsError(RuntimeError):
    """A startup-safe settings error that never includes setting values."""

    def __init__(self, keys: tuple[str, ...], action: str) -> None:
        self.keys = tuple(sorted(set(keys)))
        self.action = action
        joined = ", ".join(self.keys) if self.keys else f"{ENV_PREFIX}*"
        super().__init__(f"Invalid configuration for {joined}. {action}")


def _parse_string_list(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise ValueError("must be a JSON array or comma-separated list")
            items = parsed
        else:
            items = stripped.split(",")
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise ValueError("must be a JSON array or comma-separated list")

    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("list entries must be non-empty strings")
        normalized.append(item.strip())
    if len(normalized) != len(set(normalized)):
        raise ValueError("list entries must be unique")
    return tuple(normalized)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    _application_home: Path = PrivateAttr(default_factory=lambda: Path.cwd().resolve())

    app_name: str = "agent-shell"
    host: str = "127.0.0.1"
    port: int = Field(default=19100, ge=1, le=65535)
    allow_remote: bool = False
    langsmith_tracing_enabled: bool = False
    langsmith_endpoint: str = DEFAULT_LANGSMITH_ENDPOINT
    langsmith_project: str = "agent-shell"
    langsmith_workspace_id: str | None = None
    langsmith_api_key: SecretStr | None = None
    management_token: SecretStr | None = None
    cors_origins: Annotated[tuple[str, ...], NoDecode] = ()
    trusted_proxy_cidrs: Annotated[tuple[str, ...], NoDecode] = ()
    _data_root: Path = PrivateAttr(default_factory=lambda: (Path.cwd() / "data").resolve())

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # All non-secret settings come from system.yaml. The only Settings field
        # allowed to come from the environment is injected explicitly by
        # load_settings below: AGENT_SHELL_MANAGEMENT_TOKEN.
        return init_settings,

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("must be an IPv4 or IPv6 literal") from exc
        if getattr(address, "scope_id", None):
            raise ValueError("scoped IPv6 addresses are not supported")
        return str(address)

    @field_validator("management_token")
    @classmethod
    def validate_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if not bearer_token_is_valid(secret):
            raise ValueError(
                "must be a non-empty printable ASCII value without spaces"
            )
        return value

    @field_validator("langsmith_api_key")
    @classmethod
    def validate_langsmith_api_key(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if not bearer_token_is_valid(secret):
            raise ValueError(
                "must be a non-empty printable ASCII value without spaces"
            )
        return value

    @field_validator("langsmith_endpoint")
    @classmethod
    def validate_langsmith_endpoint(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("must be an HTTP(S) URL without userinfo, query, or fragment")
        return normalized

    @field_validator("langsmith_project")
    @classmethod
    def validate_langsmith_project(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 200:
            raise ValueError("must contain 1 to 200 characters")
        return normalized

    @field_validator("langsmith_workspace_id", mode="before")
    @classmethod
    def normalize_langsmith_workspace_id(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > 200:
            raise ValueError("must not exceed 200 characters")
        return normalized

    @field_validator("cors_origins", "trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_string_lists(cls, value: Any) -> tuple[str, ...]:
        return _parse_string_list(value)

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for origin in origins:
            if origin == "*":
                raise ValueError("wildcard origins are not supported")
            parsed = urlsplit(origin)
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError("origin port is invalid") from exc
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("must be an exact HTTP(S) origin without path or userinfo")
            scheme = parsed.scheme.lower()
            hostname = parsed.hostname.lower()
            if ":" in hostname:
                hostname = f"[{hostname}]"
            netloc = f"{hostname}:{port}" if port is not None else hostname
            normalized.append(f"{scheme}://{netloc}")
        if len(normalized) != len(set(normalized)):
            raise ValueError("normalized origins must be unique")
        return tuple(normalized)

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, cidrs: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for cidr in cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=True)
            except ValueError as exc:
                raise ValueError("must contain exact IPv4 or IPv6 CIDR networks") from exc
            normalized.append(str(network))
        if len(normalized) != len(set(normalized)):
            raise ValueError("normalized proxy networks must be unique")
        return tuple(normalized)

    @property
    def is_loopback(self) -> bool:
        return ipaddress.ip_address(self.host).is_loopback

    @property
    def deployment_mode(self) -> str:
        if self.allow_remote or not self.is_loopback or self.trusted_proxy_cidrs:
            return "authenticated_remote"
        return "authenticated_local"

    def validate_deployment(self) -> None:
        keys: set[str] = set()
        actions: list[str] = []
        if not self.is_loopback and not self.allow_remote:
            keys.update({"AGENT_SHELL_HOST", "AGENT_SHELL_ALLOW_REMOTE"})
            actions.append("Enable remote access explicitly or use a loopback host.")
        if self.trusted_proxy_cidrs and not self.allow_remote:
            keys.update(
                {"AGENT_SHELL_TRUSTED_PROXY_CIDRS", "AGENT_SHELL_ALLOW_REMOTE"}
            )
            actions.append("Trusted proxy deployment requires explicit remote access.")

        if self.management_token is None:
            keys.add("AGENT_SHELL_MANAGEMENT_TOKEN")
            actions.append("Configure the management Bearer token.")

        if self.langsmith_tracing_enabled and self.langsmith_api_key is None:
            keys.add("LANGSMITH_API_KEY")
            actions.append("Configure the LangSmith API key or disable tracing.")

        if actions:
            raise SettingsError(tuple(keys), " ".join(actions))

    @property
    def application_home(self) -> Path:
        return self._application_home

    @property
    def data_root(self) -> Path:
        return self._data_root

    @property
    def environment_file(self) -> Path:
        return self.data_root / "config" / "agent-shell.env"

    @property
    def system_file(self) -> Path:
        return self.data_root / "config" / "system.yaml"

    def bind_paths(self, application_home: Path, data_root: Path) -> None:
        self._application_home = application_home.resolve()
        self._data_root = data_root.resolve()

    def resolved_runtime_dir(self) -> Path:
        return self.application_home / "runtime"

    def resolved_logs_dir(self) -> Path:
        return self.data_root / "logs"

    def resolved_database_path(self) -> Path:
        return self.data_root / "state" / "agent-shell.sqlite3"

    def resolved_files_dir(self) -> Path:
        return self.data_root / "files"

    def resolved_media_outputs_dir(self) -> Path:
        return self.data_root / "media" / "outputs"

    def resolved_python_templates_dir(self) -> Path:
        return self.data_root / "templates"

    def resolved_python_package_instances_dir(self) -> Path:
        return ensure_active_configuration_repository(
            self.data_root
        ).python_packages_root

    def resolved_skill_templates_dir(self) -> Path:
        return self.data_root / "skills-template"

    def resolved_skill_package_instances_dir(self) -> Path:
        return ensure_active_configuration_repository(
            self.data_root
        ).skill_packages_root

    def ensure_directories(self) -> None:
        directories = (
            self.data_root / "config",
            self.data_root / "state",
            self.resolved_files_dir(),
            self.resolved_media_outputs_dir(),
            self.resolved_python_templates_dir() / "agent" / "custom_tool",
            self.resolved_python_templates_dir() / "workflow" / "command",
            self.resolved_python_templates_dir() / "workflow" / "task_dispatcher",
            self.resolved_python_templates_dir() / "workflow" / "workflow_event_output",
            self.resolved_python_templates_dir() / "agent" / "custom_middleware",
            self.resolved_python_templates_dir() / "agent" / "agent_event_output",
            self.resolved_python_package_instances_dir() / "command",
            self.resolved_python_package_instances_dir() / "task-dispatcher",
            self.resolved_python_package_instances_dir() / "agent-middleware",
            self.resolved_python_package_instances_dir() / "agent-tool",
            self.resolved_python_package_instances_dir() / "agent-event-output",
            self.resolved_python_package_instances_dir() / "workflow-event-output",
            self.resolved_skill_package_instances_dir(),
            self.resolved_skill_templates_dir(),
            self.resolved_logs_dir(),
            self.resolved_runtime_dir() / "cache",
            self.resolved_runtime_dir() / "tmp",
            self.resolved_runtime_dir() / "home",
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def _unknown_environment_keys(environment: dict[str, str]) -> tuple[str, ...]:
    return unknown_environment_names(environment)


def _error_keys(exc: ValidationError) -> tuple[str, ...]:
    keys: set[str] = set()
    for error in exc.errors(include_input=False, include_url=False):
        location = error.get("loc") or ()
        if not location:
            continue
        field = str(location[0]).upper()
        keys.add(
            field
            if field.startswith((ENV_PREFIX, "LANGSMITH_"))
            else (
                f"LANGSMITH_{field.removeprefix('LANGSMITH_')}"
                if field == "LANGSMITH_API_KEY"
                else f"{ENV_PREFIX}{field}"
            )
        )
    return tuple(keys)


def load_settings(
    *,
    application_home: Path | None = None,
    data_root: Path | None = None,
) -> Settings:
    home = (application_home or Path.cwd()).resolve()
    root = data_root or (home / "data")
    root = root.resolve() if root.is_absolute() else (home / root).resolve()
    env_path = root / "config" / "agent-shell.env"
    system_path = root / "config" / "system.yaml"
    try:
        environment_values = read_environment_file(env_path)
    except (OSError, UnicodeError, EnvironmentFormatError):
        raise SettingsError(
            ("data/config/agent-shell.env",),
            "Rewrite the secret settings through the management pages.",
        ) from None
    file_unknown = _unknown_environment_keys(environment_values)
    if file_unknown:
        raise SettingsError(
            file_unknown, "Remove or correct unknown AGENT_SHELL_* settings."
        )
    try:
        system_values: dict[str, Any] = {}
        if system_path.exists():
            with system_path.open("r", encoding="utf-8") as stream:
                document = yaml.safe_load(stream) or {}
            if not isinstance(document, dict):
                raise ValueError("system configuration must contain a mapping")
            values = document.get("settings", document)
            if not isinstance(values, dict):
                raise ValueError("system.settings must contain a mapping")
            system_values = dict(values)
        system_values.pop("management_token", None)
        system_values.pop("langsmith_api_key", None)
        management_token = environment_values.get("AGENT_SHELL_MANAGEMENT_TOKEN")
        if management_token is not None:
            system_values["management_token"] = management_token
        langsmith_api_key = environment_values.get("LANGSMITH_API_KEY")
        if langsmith_api_key is not None:
            system_values["langsmith_api_key"] = langsmith_api_key
        settings = Settings(**system_values)
    except ValidationError as exc:
        raise SettingsError(
            _error_keys(exc), "Correct the listed setting keys and restart."
        ) from None
    settings.bind_paths(home, root)
    return settings


def get_settings(
    *,
    application_home: Path | None = None,
    data_root: Path | None = None,
) -> Settings:
    settings = load_settings(
        application_home=application_home,
        data_root=data_root,
    )
    settings.validate_deployment()
    return settings
