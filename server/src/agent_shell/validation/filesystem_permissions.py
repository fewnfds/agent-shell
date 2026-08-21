from __future__ import annotations

import re
from typing import Any

from agent_shell.validation.models import ValidationIssue


_WILDCARD_START = re.compile(r"[*?{[]")


def _declared_paths(filesystem: dict[str, Any] | None) -> tuple[str, ...]:
    if filesystem is None:
        return ()
    paths: list[str] = []
    for field in ("mapped_directories", "virtual_directories", "virtual_files"):
        entries = filesystem.get(field, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("virtual_path")
            if isinstance(path, str) and path:
                paths.append(path)
    return tuple(paths)


def _can_match_declared_path(pattern: str, declared: str) -> bool:
    wildcard = _WILDCARD_START.search(pattern)
    literal_prefix = pattern[: wildcard.start()] if wildcard else pattern
    literal_prefix = literal_prefix.rstrip("/") or "/"
    declared_prefix = declared.rstrip("/") or "/"
    return (
        literal_prefix == "/"
        or declared_prefix == literal_prefix
        or declared_prefix.startswith(literal_prefix + "/")
        or literal_prefix.startswith(declared_prefix + "/")
    )


def filesystem_permission_warnings(
    blocks: dict[str, dict[str, Any]],
    *,
    scope: str,
    owner_id: str,
    owner_name: str,
) -> list[ValidationIssue]:
    permissions = blocks.get("filesystem-permissions")
    if permissions is None:
        return []
    declared = _declared_paths(blocks.get("filesystem"))
    rules = permissions.get("permissions", [])
    if not isinstance(rules, list):
        return []

    warnings: list[ValidationIssue] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        path = rule.get("path")
        if not isinstance(path, str):
            continue
        if any(_can_match_declared_path(path, item) for item in declared):
            continue
        warnings.append(
            ValidationIssue(
                code="assembly.filesystem_permission_path_unmatched",
                severity="warning",
                scope=scope,
                owner_id=owner_id,
                owner_name=owner_name,
                path=(
                    "capability_refs.filesystem-permissions."
                    f"permissions[{index}].path"
                ),
                message=(
                    f"Permission path {path!r} does not match a declared path "
                    "in this Agent's current filesystem."
                ),
                message_key=(
                    "validation.issue.assembly.filesystemPermissionPathUnmatched"
                ),
                message_args={"path": path},
            )
        )
    return warnings

