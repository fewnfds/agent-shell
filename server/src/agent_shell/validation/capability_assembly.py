from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from agent_shell.capability_manifest import CAPABILITY_MANIFESTS
from agent_shell.validation.models import ValidationIssue


FilesystemMode = Literal[
    "composite",
    "local-shell",
]


@dataclass(frozen=True, slots=True)
class CapabilityAssemblySubject:
    """One effective capability consumer at the configuration assembly boundary."""

    references: Mapping[str, str]
    scope: str
    owner_id: str = ""
    owner_name: str = ""
    required_types: frozenset[str] = field(default_factory=frozenset)

def capability_assembly_issues(
    subject: CapabilityAssemblySubject,
) -> list[ValidationIssue]:
    """Validate required capabilities and cross-capability contracts."""

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
    if "filesystem-tools" in selected_types and "filesystem" not in selected_types:
        issues.append(
            ValidationIssue(
                code="assembly.filesystem_backend_required",
                scope=subject.scope,
                owner_id=subject.owner_id,
                owner_name=subject.owner_name,
                path="capability_refs.filesystem",
                message="Filesystem Tools require a Filesystem Backend.",
                message_key="validation.issue.assembly.filesystemBackendRequired",
                message_args={},
            )
        )
    if "summarization" in selected_types and "filesystem-tools" not in selected_types:
        issues.append(
            ValidationIssue(
                code="assembly.summarization_archive_unreadable",
                scope=subject.scope,
                owner_id=subject.owner_id,
                owner_name=subject.owner_name,
                path="capability_refs.filesystem-tools",
                message=(
                    "Summarization can archive history without Filesystem Tools, "
                    "but the model cannot read the archived history again."
                ),
                message_key=(
                    "validation.issue.assembly.summarizationArchiveUnreadable"
                ),
                message_args={},
                severity="warning",
            )
        )
    return issues
