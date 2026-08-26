from __future__ import annotations

from agent_shell.configuration.dependencies import (
    ConfigurationEntity,
    ConfigurationReference,
)
from agent_shell.validation.models import ValidationIssue


REFERENCE_ISSUE_CODES = frozenset(
    {
        "configuration.reference_not_found",
        "configuration.reference_type_mismatch",
    }
)


def reference_target_type(reference: ConfigurationReference) -> str:
    return reference.target_component_type or reference.target_kind


def reference_target_matches(
    target: ConfigurationEntity,
    reference: ConfigurationReference,
) -> bool:
    return target.kind == reference.target_kind and (
        reference.target_kind != "component"
        or target.component_type == reference.target_component_type
    )


def reference_not_found_issue(
    *,
    scope: str,
    owner_id: str,
    owner_name: str,
    owner_type: str,
    path: str,
    reference_id: str,
    expected_type: str,
) -> ValidationIssue:
    return ValidationIssue(
        code="configuration.reference_not_found",
        scope=scope,
        owner_id=owner_id,
        owner_name=owner_name,
        owner_type=owner_type,
        path=path,
        message=f"The referenced {expected_type} configuration does not exist.",
        message_key="validation.issue.configuration.referenceNotFound",
        message_args={
            "expected_type": expected_type,
            "reference_id": reference_id,
        },
    )


def reference_type_mismatch_issue(
    *,
    scope: str,
    owner_id: str,
    owner_name: str,
    owner_type: str,
    path: str,
    reference_id: str,
    expected_type: str,
    actual_type: str,
) -> ValidationIssue:
    return ValidationIssue(
        code="configuration.reference_type_mismatch",
        scope=scope,
        owner_id=owner_id,
        owner_name=owner_name,
        owner_type=owner_type,
        path=path,
        message=(
            f"The referenced UUID belongs to {actual_type}, not {expected_type}."
        ),
        message_key="validation.issue.configuration.referenceTypeMismatch",
        message_args={
            "actual_type": actual_type,
            "expected_type": expected_type,
            "reference_id": reference_id,
        },
    )


def configuration_reference_issue(
    owner: ConfigurationEntity,
    reference: ConfigurationReference,
    target: ConfigurationEntity | None,
) -> ValidationIssue | None:
    common = {
        "scope": "block" if owner.kind == "component" else owner.kind,
        "owner_id": owner.id,
        "owner_name": owner.name,
        "owner_type": owner.component_type or owner.kind,
        "path": reference.path,
        "reference_id": reference.target_id,
        "expected_type": reference_target_type(reference),
    }
    if target is None:
        return reference_not_found_issue(**common)
    if reference_target_matches(target, reference):
        return None
    return reference_type_mismatch_issue(
        **common,
        actual_type=target.component_type or target.kind,
    )


__all__ = [
    "REFERENCE_ISSUE_CODES",
    "configuration_reference_issue",
    "reference_not_found_issue",
    "reference_target_matches",
    "reference_target_type",
    "reference_type_mismatch_issue",
]
