from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from agent_shell.capability_manifest import CAPABILITY_MANIFESTS
from agent_shell.validation.models import ValidationIssue


FilesystemMode = Literal[
    "default-shared",
    "configured-shared",
]


@dataclass(frozen=True, slots=True)
class CapabilityAssemblySubject:
    """One effective capability consumer at the configuration assembly boundary."""

    references: Mapping[str, str]
    scope: str
    owner_id: str = ""
    owner_name: str = ""
    required_types: frozenset[str] = field(default_factory=frozenset)

    @property
    def filesystem_mode(self) -> FilesystemMode:
        if "filesystem" in self.references:
            return "configured-shared"
        return "default-shared"


def capability_assembly_issues(
    subject: CapabilityAssemblySubject,
) -> list[ValidationIssue]:
    """Validate required capabilities for one resolved consumer."""

    selected_types = set(subject.references)
    issues: list[ValidationIssue] = []
    for manifest in CAPABILITY_MANIFESTS:
        if (
            manifest.type in subject.required_types
            and manifest.type not in selected_types
        ):
            issues.append(
                ValidationIssue(
                    code="assembly.required_capability_missing",
                    scope=subject.scope,
                    owner_id=subject.owner_id,
                    owner_name=subject.owner_name,
                    path=f"capability_refs.{manifest.type}",
                    message=f"A {manifest.type} configuration must be selected.",
                    message_key="validation.issue.assembly.requiredCapabilityMissing",
                    message_args={"capability_type": manifest.type},
                )
            )
    return issues
