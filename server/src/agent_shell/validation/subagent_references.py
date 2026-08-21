from __future__ import annotations

from typing import Any

from agent_shell.configuration.identity import name_collision_key
from agent_shell.validation.models import ValidationIssue


def subagent_reference_issues(
    references: list[dict[str, Any]],
    *,
    profiles: dict[str, dict[str, Any]],
    scope: str,
    owner_id: str,
    owner_name: str,
    path_prefix: str = "subagents",
) -> list[ValidationIssue]:
    """Return direct-child identity conflicts after references are resolved."""

    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, reference in enumerate(references):
        subagent_id = str(reference.get("subagent_id", ""))
        common = {
            "scope": scope,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "message_args": {},
        }
        if subagent_id in seen_ids:
            issues.append(
                ValidationIssue(
                    code="contract.subagent_reference_duplicate",
                    path=f"{path_prefix}[{index}].subagent_id",
                    message="The same Subagent entity cannot be attached twice.",
                    message_key=(
                        "validation.issue.contract.subagentReferenceDuplicate"
                    ),
                    **common,
                )
            )
            continue
        seen_ids.add(subagent_id)
        profile = profiles.get(subagent_id)
        if profile is None:
            continue
        name = name_collision_key(str(profile.get("name", "")))
        if name in seen_names:
            issues.append(
                ValidationIssue(
                    code="contract.subagent_name_duplicate",
                    path=f"{path_prefix}[{index}].subagent_id",
                    message="Direct child Subagent routing names must be unique.",
                    message_key="validation.issue.contract.subagentNameDuplicate",
                    **common,
                )
            )
        else:
            seen_names.add(name)
    return issues
