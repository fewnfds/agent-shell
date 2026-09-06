from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_shell.configuration.dependencies import ConfigurationEntityKind
from agent_shell.configuration.identity import ConfigurationId, ConfigurationName


BUNDLE_FORMAT = "agent-shell.configuration-bundle"
BUNDLE_FORMAT_VERSION = 4


class BundleRoot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: ConfigurationEntityKind
    source_id: ConfigurationId
    component_type: str | None = Field(default=None, alias="type")

    @model_validator(mode="after")
    def validate_component_type(self) -> "BundleRoot":
        if (self.kind == "component") != (self.component_type is not None):
            raise ValueError("type is required only for a component root")
        return self


class BundleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    kind: ConfigurationEntityKind
    source_id: ConfigurationId
    name: ConfigurationName
    component_type: str | None = Field(default=None, alias="type")
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_component_type(self) -> "BundleRecord":
        if (self.kind == "component") != (self.component_type is not None):
            raise ValueError("type is required only for component records")
        forbidden = {
            "id",
            (
                "component_name"
                if self.kind in {"subagent", "async_subagent"}
                else "name"
            ),
        }
        if forbidden.intersection(self.payload):
            raise ValueError("bundle record payload duplicates envelope identity")
        return self


class PythonPackageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["python-package"]
    owner_source_id: ConfigurationId
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillPackageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["skill-package"]
    owner_source_id: ConfigurationId
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


BundleAsset = Annotated[
    PythonPackageAsset | SkillPackageAsset,
    Field(discriminator="kind"),
]


class BundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal[BUNDLE_FORMAT] = BUNDLE_FORMAT
    format_version: Literal[BUNDLE_FORMAT_VERSION] = BUNDLE_FORMAT_VERSION
    source_application_version: str = Field(min_length=1)
    root: BundleRoot
    records: list[BundleRecord] = Field(min_length=1)
    assets: list[BundleAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identities(self) -> "BundleManifest":
        record_ids = [record.source_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("bundle record source_id values must be unique")
        asset_keys = [
            (asset.kind, asset.owner_source_id)
            if isinstance(asset, (PythonPackageAsset, SkillPackageAsset))
            else (asset.kind, "")
            for asset in self.assets
        ]
        if len(asset_keys) != len(set(asset_keys)):
            raise ValueError("bundle asset owners must be unique")
        if self.root.source_id not in set(record_ids):
            raise ValueError("bundle root must identify one bundled record")
        root_record = next(
            record for record in self.records if record.source_id == self.root.source_id
        )
        if (
            root_record.kind != self.root.kind
            or root_record.component_type != self.root.component_type
        ):
            raise ValueError("bundle root kind and type must match its record")
        record_keys = [
            (record.kind, record.component_type or "", record.source_id)
            for record in self.records
        ]
        if record_keys != sorted(record_keys):
            raise ValueError("bundle records must use canonical ordering")
        asset_keys = [
            (
                asset.kind,
                getattr(asset, "owner_source_id", ""),
                getattr(asset, "name", ""),
            )
            for asset in self.assets
        ]
        if asset_keys != sorted(asset_keys):
            raise ValueError("bundle assets must use canonical ordering")
        return self


class FilesystemBindingResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: str = Field(min_length=1)
    path_origin: Literal["absolute", "data-root-relative"] | None = None


class ImportResolutions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ids: dict[ConfigurationId, ConfigurationId]
    names: dict[ConfigurationId, ConfigurationName] = Field(default_factory=dict)
    filesystem_bindings: dict[str, FilesystemBindingResolution] = Field(
        default_factory=dict
    )


__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_FORMAT_VERSION",
    "BundleAsset",
    "BundleManifest",
    "BundleRecord",
    "BundleRoot",
    "FilesystemBindingResolution",
    "ImportResolutions",
    "PythonPackageAsset",
    "SkillPackageAsset",
]
