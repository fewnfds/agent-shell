from __future__ import annotations

import os
import posixpath
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from agent_shell.capability_manifest import (
    CAPABILITY_BY_TYPE,
    CAPABILITY_MANIFESTS,
    PUBLIC_CAPABILITY_MANIFESTS,
    validate_capability_manifests,
)
from agent_shell.configuration.identity import ConfigurationId, ConfigurationName
from agent_shell.command import CommandBlock
from agent_shell.model_provider_contracts import validate_provider_settings
from agent_shell.provider_integrations import bundled_provider_ids
from agent_shell.response_stream_policy import ResponseQueuePolicy
from agent_shell.storage.owned_paths import (
    is_reparse_point,
    require_data_root_relative_path,
)
from agent_shell.task_dispatcher import TaskDispatcherBlock
from agent_shell.workflow_event_output import WorkflowEventOutputBlock


SKILL_PROMPT_FIELDS = (
    "skills_locations",
    "skills_load_warnings",
    "skills_list",
)
from agent_shell.python_packages.contracts import PackageFolder, PythonPackageReference
TASK_DESCRIPTION_FIELDS = ("available_agents",)


BlockName = ConfigurationName
LocalPath = Annotated[str, Field(max_length=4096)]
VirtualPath = Annotated[str, Field(min_length=1, max_length=4096)]
DescriptionDraft = Annotated[str, Field(max_length=100_000)]
PromptOverrideText = Annotated[
    str,
    StringConstraints(strip_whitespace=False),
    Field(max_length=100_000),
]
ModelBoolean = Annotated[bool, Field(strict=True)]
ModelText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
    Field(max_length=120),
]
BlockReference = ConfigurationId | Literal[""]
RequiredReference = ConfigurationId
# Keep user-authored filesystem targets out of upstream framework namespaces.
# Agent Shell enforces this input boundary but does not manage those directories.
RESERVED_VIRTUAL_NAMESPACES = (
    "/large_tool_results/",
    "/conversation_history/",
    "/skills/",
    "/memory/",
    "/memories/",
)


def _validate_format_template(
    value: str,
    *,
    allowed_fields: tuple[str, ...],
    label: str,
    required_fields: tuple[str, ...] | None = None,
) -> str:
    seen: set[str] = set()
    try:
        parsed = Formatter().parse(value)
        for _literal, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if field_name not in allowed_fields:
                raise ValueError(
                    f"{label} contains an unsupported placeholder: {{{field_name}}}"
                )
            if format_spec or conversion:
                raise ValueError(
                    f"{label} placeholders do not support format specifications or conversions: {{{field_name}}}"
                )
            seen.add(field_name)
        index = 0
        while index < len(value):
            if value[index : index + 2] in {"{{", "}}"}:
                index += 2
                continue
            if value[index] != "{":
                index += 1
                continue
            end = value.find("}", index + 1)
            expression = value[index + 1 : end]
            if expression not in allowed_fields:
                raise ValueError(
                    f"{label} accepts only complete placeholders: {{{expression}}}"
                )
            index = end + 1
    except ValueError as exc:
        if str(exc).startswith(label):
            raise
        raise ValueError(
            f"{label} contains invalid braces; literal braces must be written as {{{{ and }}}}"
        ) from None

    required = allowed_fields if required_fields is None else required_fields
    missing = [field for field in required if field not in seen]
    if missing:
        raise ValueError(
            f"{label} is missing required placeholders: "
            + ", ".join(f"{{{field}}}" for field in missing)
        )
    return value


def _validate_virtual_path(value: str) -> str:
    value = value.replace("\\", "/")
    if not value.startswith("/"):
        raise ValueError("virtual path must start with /")
    if any(part == ".." for part in value.split("/")):
        raise ValueError("virtual path must not contain ..")
    normalized = posixpath.normpath(value)
    return "/" + normalized.lstrip("/")


def _validate_virtual_directory_path(value: str) -> str:
    if not value.replace("\\", "/").endswith("/"):
        raise ValueError("virtual directory path must end with /")
    normalized = _validate_virtual_path(value)
    return "/" if normalized == "/" else normalized.rstrip("/") + "/"


def _validate_virtual_file_path(value: str) -> str:
    if value.replace("\\", "/").endswith("/"):
        raise ValueError("virtual file path must not end with /")
    normalized = _validate_virtual_path(value)
    if normalized == "/":
        raise ValueError("virtual file path must include a file name")
    return normalized


def _validate_local_path(value: str) -> str:
    if value and not Path(value).is_absolute():
        raise ValueError("local path must be absolute")
    return value


def _validate_required_local_path(value: str) -> str:
    if not value:
        raise ValueError("local path must not be empty")
    return _validate_local_path(value)


def _reserved_virtual_namespace(path: str, *, is_directory: bool) -> str | None:
    for namespace in RESERVED_VIRTUAL_NAMESPACES:
        if path.startswith(namespace):
            return namespace
        if is_directory and namespace.startswith(path):
            return namespace
        if not is_directory and path == namespace.rstrip("/"):
            return namespace
    return None


class StrictBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: BlockName


CheckpointDurability = Literal["exit", "async", "sync"]


class CheckpointerBlock(StrictBlock):
    durability: CheckpointDurability = "async"


class ResponseStreamSchedulingBlock(StrictBlock):
    queue: ResponseQueuePolicy = Field(default_factory=ResponseQueuePolicy)


CredentialValue = Annotated[
    str,
    StringConstraints(strip_whitespace=False),
    Field(min_length=1, max_length=4096),
]
CREDENTIAL_VALUE_ADAPTER = TypeAdapter(CredentialValue | None)


def _reject_masked_credential(value: str | None) -> str | None:
    if value is not None and len(value) >= 4 and set(value) <= {"*", "•"}:
        raise ValueError("masked secret text cannot replace a credential")
    return value


class ModelConnectionBlock(StrictBlock):
    provider: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"),
    ]
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    credential: CredentialValue | None
    model: Annotated[str, Field(min_length=1, max_length=240)]
    provider_settings: dict[str, JsonValue]
    tool_choice: ModelText | ModelBoolean | dict[str, JsonValue] | None
    response_format: dict[str, JsonValue] | None
    model_settings: dict[str, JsonValue]

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value not in bundled_provider_ids():
            raise ValueError(
                "provider must be bundled with this Agent Shell version"
            )
        return value

    @model_validator(mode="after")
    def validate_settings_for_provider(self) -> ModelConnectionBlock:
        if self.provider == "google_vertexai" and self.credential is not None:
            raise ValueError(
                "google_vertexai uses Application Default Credentials"
            )
        self.provider_settings = validate_provider_settings(
            self.provider,
            self.provider_settings,
        )
        return self

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) URL")
        return value.rstrip("/")

    @field_validator("credential")
    @classmethod
    def validate_credential(cls, value: str | None) -> str | None:
        return _reject_masked_credential(value)

    @field_validator("model_settings")
    @classmethod
    def validate_model_settings(
        cls, value: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        reserved = sorted(set(value) & {"response_format", "tool_choice", "tools"})
        if reserved:
            raise ValueError(
                "model_settings contains dedicated ModelRequest fields: "
                + ", ".join(reserved)
            )
        return value

    @field_validator("response_format")
    @classmethod
    def validate_response_format(
        cls, value: dict[str, JsonValue] | None
    ) -> dict[str, JsonValue] | None:
        if value is None:
            return None
        missing = [
            field
            for field in ("title", "description")
            if not isinstance(value.get(field), str) or not value[field].strip()
        ]
        if missing:
            raise ValueError(
                "response_format JSON Schema requires non-empty: "
                + ", ".join(missing)
            )
        return value


class ModelRequirementBlock(StrictBlock):
    """Portable model capability requirement.

    Provider credentials and model connection settings are instance-owned and
    deliberately do not belong in a Configuration Repository.
    """

    description: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1),
        Field(max_length=100_000),
    ]


class CustomToolBlock(StrictBlock):
    python_package: PythonPackageReference


class CustomMiddlewareBlock(StrictBlock):
    python_package: PythonPackageReference


class AgentEventOutputBlock(StrictBlock):
    python_package: PythonPackageReference


ExceptionRetryStrategy = Literal["provider_native", "model_retry_middleware"]
EXCEPTION_RETRY_STRATEGIES = (
    "provider_native",
    "model_retry_middleware",
)
ExceptionRetryCondition = Literal[
    "transport_error",
    "timeout",
    "rate_limit",
    "server_error",
    "authentication_error",
]
EXCEPTION_RETRY_CONDITIONS = (
    "transport_error",
    "timeout",
    "rate_limit",
    "server_error",
    "authentication_error",
)
DEFAULT_EXCEPTION_RETRY_CONDITIONS = (
    "transport_error",
    "timeout",
    "rate_limit",
    "server_error",
)


class ExceptionRetryBlock(StrictBlock):
    strategy: ExceptionRetryStrategy = "provider_native"
    force_non_streaming: bool = False
    max_retries: Annotated[int, Field(strict=True, ge=0)] = 2
    retry_on: list[ExceptionRetryCondition] = Field(
        default_factory=lambda: list(DEFAULT_EXCEPTION_RETRY_CONDITIONS),
        max_length=len(EXCEPTION_RETRY_CONDITIONS),
    )

    @field_validator("retry_on")
    @classmethod
    def unique_retry_conditions(
        cls, values: list[ExceptionRetryCondition]
    ) -> list[ExceptionRetryCondition]:
        if len(values) != len(set(values)):
            raise ValueError("retry_on conditions must be unique")
        return values


class SystemPromptBlock(StrictBlock):
    system_prompt: Annotated[str, Field(min_length=1, max_length=200_000)]


FilesystemPermissionValue = Literal["read-write", "read-only", "no-access"]


class VirtualDirectorySource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    virtual_path: VirtualPath
    source_path: LocalPath
    permission: FilesystemPermissionValue = "read-write"

    _virtual_path = field_validator("virtual_path")(_validate_virtual_directory_path)
    _source_path = field_validator("source_path")(_validate_required_local_path)


class MappedDirectory(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    virtual_path: VirtualPath
    local_path: LocalPath
    path_origin: Literal["absolute", "data-root-relative"] = "absolute"
    lifecycle_mode: Literal["fixed", "dynamic"] = "fixed"
    permission: FilesystemPermissionValue = "read-write"

    _virtual_path = field_validator("virtual_path")(_validate_virtual_directory_path)

    @model_validator(mode="after")
    def validate_local_path(self) -> "MappedDirectory":
        if not self.local_path:
            raise ValueError("local path must not be empty")
        local = Path(self.local_path)
        if self.path_origin == "absolute":
            if not local.is_absolute():
                raise ValueError("absolute mapped local_path must be absolute")
            return self
        require_data_root_relative_path(
            self.local_path,
            label="data-root-relative mapped local_path",
        )
        return self


class VirtualFileSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    virtual_path: VirtualPath
    source_path: LocalPath
    permission: FilesystemPermissionValue = "read-write"

    _virtual_path = field_validator("virtual_path")(_validate_virtual_file_path)
    _source_path = field_validator("source_path")(_validate_required_local_path)


class FilesystemToolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible: bool = True
    description_override: PromptOverrideText | None = None


class RequiredFilesystemToolConfig(FilesystemToolConfig):
    visible: Literal[True] = True


class OptionalFilesystemToolConfig(FilesystemToolConfig):
    visible: bool = False


class FilesystemToolConfigs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ls: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    read_file: RequiredFilesystemToolConfig = Field(
        default_factory=RequiredFilesystemToolConfig
    )
    write_file: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    edit_file: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    delete: OptionalFilesystemToolConfig = Field(
        default_factory=OptionalFilesystemToolConfig
    )
    glob: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    grep: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    execute: OptionalFilesystemToolConfig = Field(
        default_factory=OptionalFilesystemToolConfig
    )


class FilesystemWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    local_path: LocalPath
    path_origin: Literal["absolute", "data-root-relative"] = "absolute"

    @model_validator(mode="after")
    def validate_local_path(self) -> "FilesystemWorkspace":
        if not self.local_path:
            raise ValueError("workspace local_path must not be empty")
        local = Path(self.local_path)
        if self.path_origin == "absolute":
            if not local.is_absolute():
                raise ValueError("absolute workspace local_path must be absolute")
            if not local.is_dir():
                raise ValueError(
                    f"workspace local_path must be an existing directory: {local}"
                )
            return self
        require_data_root_relative_path(
            self.local_path,
            label="data-root-relative workspace local_path",
        )
        return self


class FilesystemBlock(StrictBlock):
    backend_type: Literal["composite", "local-shell"] = "composite"
    mapped_directories: list[MappedDirectory] = Field(default_factory=list)
    virtual_directories: list[VirtualDirectorySource] = Field(default_factory=list)
    virtual_files: list[VirtualFileSource] = Field(default_factory=list)
    workspace: FilesystemWorkspace | None = None
    skill_package_id: ConfigurationId | None = None
    system_prompt_override: PromptOverrideText | None = None

    @model_validator(mode="after")
    def validate_backend_type(self) -> "FilesystemBlock":
        has_composite_sources = bool(
            self.mapped_directories or self.virtual_directories or self.virtual_files
        )
        if self.backend_type == "local-shell":
            if self.workspace is None:
                raise ValueError("LocalShellBackend requires one workspace")
            if has_composite_sources:
                raise ValueError(
                    "LocalShellBackend does not accept CompositeBackend sources"
                )
            if self.skill_package_id is not None:
                raise ValueError("LocalShellBackend does not accept a Skill package")
            return self
        if self.workspace is not None:
            raise ValueError("CompositeBackend does not accept a LocalShell workspace")
        return self

    @model_validator(mode="after")
    def validate_filesystem_paths(self) -> "FilesystemBlock":
        if self.backend_type == "local-shell":
            return self
        directory_items = [*self.mapped_directories, *self.virtual_directories]
        for item in directory_items:
            namespace = _reserved_virtual_namespace(
                item.virtual_path, is_directory=True
            )
            if namespace is not None:
                raise ValueError(
                    "virtual directory overlaps a reserved system namespace: "
                    f"{item.virtual_path}, {namespace}"
                )
        for item in self.virtual_files:
            namespace = _reserved_virtual_namespace(
                item.virtual_path, is_directory=False
            )
            if namespace is not None:
                raise ValueError(
                    "virtual file uses a reserved system namespace: "
                    f"{item.virtual_path}, {namespace}"
                )

        mapped_paths = [item.virtual_path for item in self.mapped_directories]
        for index, path in enumerate(mapped_paths):
            for other in mapped_paths[index + 1 :]:
                if path.startswith(other) or other.startswith(path):
                    raise ValueError(
                        f"mapped directory routes must not overlap: {path}, {other}"
                    )

        virtual_directory_paths = [item.virtual_path for item in self.virtual_directories]
        if len(virtual_directory_paths) != len(set(virtual_directory_paths)):
            raise ValueError("virtual directory targets must be unique")

        mapped_local_paths: set[str] = set()
        for item in self.mapped_directories:
            local = Path(item.local_path)
            if item.path_origin == "absolute" and not local.is_dir():
                raise ValueError(f"mapped local_path must be an existing directory: {local}")
            canonical = (
                os.path.normcase(str(local.resolve()))
                if item.path_origin == "absolute"
                else f"data-root-relative:{os.path.normcase(str(local))}"
            )
            if canonical in mapped_local_paths:
                raise ValueError(f"mapped local directories must be unique: {local}")
            mapped_local_paths.add(canonical)

        for item in self.virtual_directories:
            source = Path(item.source_path)
            if is_reparse_point(source):
                raise ValueError(
                    "virtual directory source_path must not be a link or reparse point: "
                    f"{source}"
                )
            if not source.is_dir():
                raise ValueError(
                    f"virtual directory source_path must be an existing directory: {source}"
                )
            for route in mapped_paths:
                if item.virtual_path.startswith(route) or route.startswith(item.virtual_path):
                    raise ValueError(
                        "virtual and mapped directories must not overlap: "
                        f"{item.virtual_path}, {route}"
                    )

        target_origins: dict[str, str] = {}
        directory_origins: dict[str, str] = {}
        for item in self.virtual_directories:
            source = Path(item.source_path)
            directory_key = item.virtual_path.rstrip("/")
            previous_directory = directory_origins.get(directory_key)
            if previous_directory is not None:
                raise ValueError(
                    "virtual directory target conflicts: "
                    f"{item.virtual_path} ({previous_directory}, {source})"
                )
            directory_origins[directory_key] = str(source)
            for filepath in sorted(source.rglob("*")):
                if is_reparse_point(filepath):
                    raise ValueError(
                        "virtual directory source must not contain links or reparse points: "
                        f"{filepath}"
                    )
                relative = filepath.relative_to(source).as_posix()
                target = f"{item.virtual_path}{relative}"
                if filepath.is_dir():
                    if target in target_origins:
                        raise ValueError(
                            "virtual target cannot be both file and directory: "
                            f"{target}"
                        )
                    previous_directory = directory_origins.get(target)
                    if previous_directory is not None:
                        raise ValueError(
                            "virtual directory target conflicts: "
                            f"{target}/ ({previous_directory}, {filepath})"
                        )
                    directory_origins[target] = str(filepath)
                    continue
                if not filepath.is_file():
                    continue
                if target in directory_origins:
                    raise ValueError(
                        f"virtual target cannot be both file and directory: {target}"
                    )
                previous = target_origins.get(target)
                if previous is not None:
                    raise ValueError(
                        f"virtual file target conflicts: {target} ({previous}, {filepath})"
                    )
                target_origins[target] = str(filepath)

        for item in self.virtual_files:
            source = Path(item.source_path)
            if is_reparse_point(source):
                raise ValueError(
                    "virtual file source_path must not be a link or reparse point: "
                    f"{source}"
                )
            if not source.is_file():
                raise ValueError(
                    f"virtual file source_path must be an existing file: {source}"
                )
            if PurePosixPath(item.virtual_path).name != source.name:
                raise ValueError(
                    "virtual file name must match source file name: "
                    f"{item.virtual_path}, {source.name}"
                )
            for route in mapped_paths:
                if item.virtual_path.startswith(route):
                    raise ValueError(
                        f"virtual file target is hidden by mapped directory: {item.virtual_path}"
                    )
            if item.virtual_path in directory_origins:
                raise ValueError(
                    f"virtual target cannot be both file and directory: {item.virtual_path}"
                )
            previous = target_origins.get(item.virtual_path)
            if previous is not None:
                raise ValueError(
                    "virtual file target conflicts: "
                    f"{item.virtual_path} ({previous}, {source})"
                )
            target_origins[item.virtual_path] = str(source)

        return self


class FilesystemToolsBlock(StrictBlock):
    tool_token_limit_before_evict: Annotated[int, Field(ge=1)] | None = 20_000
    human_message_token_limit_before_evict: Annotated[int, Field(ge=1)] | None = 50_000
    grep_max_count: Annotated[int, Field(ge=1)] = 1_000
    max_execute_timeout: Annotated[int, Field(ge=1)] = 3_600
    tool_configs: FilesystemToolConfigs = Field(default_factory=FilesystemToolConfigs)


class SkillBlock(StrictBlock):
    class SkillPackageReference(BaseModel):
        model_config = ConfigDict(extra="forbid")

        folder: PackageFolder

    skill_package: SkillPackageReference
    system_prompt_enabled: bool = True
    instruction_override: PromptOverrideText | None = None

    @model_validator(mode="after")
    def validate_system_prompt_override(self) -> "SkillBlock":
        prompt = self.instruction_override
        if not self.system_prompt_enabled:
            if prompt is not None:
                raise ValueError(
                    "instruction_override must be null when the Skill system prompt is disabled"
                )
            return self
        if prompt is None:
            return self
        _validate_format_template(
            prompt,
            allowed_fields=SKILL_PROMPT_FIELDS,
            label="Skill instructions",
        )
        return self


class SubagentBlock(StrictBlock):
    instruction_override: PromptOverrideText | None = None
    task_description_override: PromptOverrideText | None = None

    @model_validator(mode="after")
    def validate_overrides(self) -> "SubagentBlock":
        task = self.task_description_override
        if task is not None:
            _validate_format_template(
                task,
                allowed_fields=TASK_DESCRIPTION_FIELDS,
                label="Subagent task description",
            )
        return self


SummarizationThresholdType = Literal["auto", "fraction", "tokens", "messages"]


class SummarizationThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SummarizationThresholdType = "auto"
    value: Annotated[int | float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "SummarizationThreshold":
        if self.type == "auto":
            if self.value is not None:
                raise ValueError("auto summarization thresholds must not have a value")
            return self
        if self.value is None:
            raise ValueError("summarization thresholds require a value")
        if self.type == "fraction" and self.value > 1:
            raise ValueError("fraction thresholds must be between 0 and 1")
        if self.type in {"tokens", "messages"} and (
            isinstance(self.value, bool) or not isinstance(self.value, int)
        ):
            raise ValueError(f"{self.type} thresholds require an integer value")
        return self


class SummarizationBlock(StrictBlock):
    trigger: SummarizationThreshold = Field(default_factory=SummarizationThreshold)
    keep: SummarizationThreshold = Field(default_factory=SummarizationThreshold)
    truncate_args_enabled: bool = True
    truncate_args_trigger: SummarizationThreshold = Field(
        default_factory=SummarizationThreshold
    )
    truncate_args_keep: SummarizationThreshold = Field(
        default_factory=SummarizationThreshold
    )
    truncate_args_max_length: Annotated[int, Field(ge=1)] = 2_000
    truncate_args_text: PromptOverrideText = "...(argument truncated)"
    trim_tokens_to_summarize: Annotated[int, Field(ge=1)] | None = 4_000
    summary_prompt_override: PromptOverrideText | None = None


class PromptCachingBlock(StrictBlock):
    type: Literal["ephemeral"] = "ephemeral"
    ttl: Literal["5m", "1h"] = "5m"
    min_messages_to_cache: Annotated[int, Field(ge=0)] = 0


class TodoListBlock(StrictBlock):
    system_prompt_override: PromptOverrideText | None = None
    tool_description_override: PromptOverrideText | None = None


class SubagentReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subagent_id: RequiredReference


class CapabilityReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Annotated[str, Field(min_length=1, max_length=120)]
    block_id: RequiredReference

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        manifest = CAPABILITY_BY_TYPE.get(value)
        if manifest is None:
            raise ValueError(f"unknown Main Agent capability: {value}")
        if not manifest.agent_selectable:
            raise ValueError(f"capability is not selectable by an Agent: {value}")
        if value in {"custom-middleware", "custom-tool"}:
            raise ValueError(
                f"{value} must be selected through its ordered reference list"
            )
        return value


class MiddlewareReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    middleware_id: RequiredReference


class ToolReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tool_id: RequiredReference


class MainAgentProfile(StrictBlock):
    capability_refs: list[CapabilityReference] = Field(default_factory=list)
    tool_refs: list[ToolReference] = Field(default_factory=list)
    middleware_refs: list[MiddlewareReference] = Field(default_factory=list)
    subagents: list[SubagentReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self) -> "MainAgentProfile":
        capability_types = [item.type for item in self.capability_refs]
        if len(capability_types) != len(set(capability_types)):
            raise ValueError("Main Agent capability_refs must contain at most one item per type")
        tool_ids = [item.tool_id for item in self.tool_refs]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("Main Agent tool_refs must not contain duplicates")
        middleware_ids = [item.middleware_id for item in self.middleware_refs]
        if len(middleware_ids) != len(set(middleware_ids)):
            raise ValueError("Main Agent middleware_refs must not contain duplicates")
        return self


class CapabilityOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Annotated[str, Field(min_length=1, max_length=120)]
    mode: Literal["replace", "disabled"]
    block_id: BlockReference = ""

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        manifest = CAPABILITY_BY_TYPE.get(value)
        if (
            manifest is None
            or value in {"custom-middleware", "custom-tool"}
            or not manifest.agent_selectable
            or not manifest.subagent_overrideable
        ):
            raise ValueError(f"capability is not overrideable by Subagent: {value}")
        return value

    @model_validator(mode="after")
    def validate_replace(self) -> "CapabilityOverride":
        manifest = CAPABILITY_BY_TYPE[self.type]
        if self.mode == "disabled" and manifest.required:
            raise ValueError(f"required capability cannot be disabled: {self.type}")
        if self.mode == "replace" and not self.block_id:
            raise ValueError("replace mode requires block_id")
        if self.mode == "disabled" and self.block_id:
            raise ValueError("disabled mode must not include block_id")
        return self


class SubagentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    capability_overrides: list[CapabilityOverride] = Field(default_factory=list)
    tool_refs: list[ToolReference] = Field(default_factory=list)
    middleware_refs: list[MiddlewareReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_overrides(self) -> "SubagentSettings":
        capability_types = [item.type for item in self.capability_overrides]
        if len(capability_types) != len(set(capability_types)):
            raise ValueError(
                "Subagent capability_overrides must contain at most one item per type"
            )
        tool_ids = [item.tool_id for item in self.tool_refs]
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("Subagent tool_refs must not contain duplicates")
        middleware_ids = [item.middleware_id for item in self.middleware_refs]
        if len(middleware_ids) != len(set(middleware_ids)):
            raise ValueError("Subagent middleware_refs must not contain duplicates")
        return self


class SubagentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    component_name: BlockName
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$",
        ),
    ]
    description: Annotated[str, Field(min_length=1, max_length=100_000)]
    settings: SubagentSettings = Field(default_factory=SubagentSettings)


BLOCK_MODELS: dict[str, type[StrictBlock]] = {
    "model-requirement": ModelRequirementBlock,
    "system-prompt": SystemPromptBlock,
    "filesystem": FilesystemBlock,
    "filesystem-tools": FilesystemToolsBlock,
    "todo-list": TodoListBlock,
    "custom-tool": CustomToolBlock,
    "skill": SkillBlock,
    "custom-middleware": CustomMiddlewareBlock,
    "agent-event-output": AgentEventOutputBlock,
    "exception-retry": ExceptionRetryBlock,
    "subagent": SubagentBlock,
    "summarization": SummarizationBlock,
    "prompt-caching": PromptCachingBlock,
}

validate_capability_manifests(CAPABILITY_MANIFESTS, BLOCK_MODELS)
BLOCK_CATALOG = PUBLIC_CAPABILITY_MANIFESTS
WORKFLOW_COMPONENT_MODELS = {
    "checkpointer": CheckpointerBlock,
    "workflow-event-output": WorkflowEventOutputBlock,
    "response-stream-scheduling": ResponseStreamSchedulingBlock,
    "command": CommandBlock,
    "task-dispatcher": TaskDispatcherBlock,
}
MANAGED_COMPONENT_MODELS = {**BLOCK_MODELS, **WORKFLOW_COMPONENT_MODELS}

def validate_provider_credential(payload: object) -> str | None:
    value = CREDENTIAL_VALUE_ADAPTER.validate_python(payload)
    return _reject_masked_credential(value)
