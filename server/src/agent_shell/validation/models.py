from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from agent_shell.localization import (
    MessageArg,
    normalize_message_args,
    normalize_message_key,
)
from agent_shell.redaction import redact_for_boundary


def _safe_report_text(value: str) -> str:
    safe = redact_for_boundary("preflight-diagnostic", value)
    return safe if isinstance(safe, str) else "[UNAVAILABLE]"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    scope: str
    path: str
    message: str
    message_key: str
    message_args: Mapping[str, MessageArg] = field(default_factory=dict)
    owner_id: str = ""
    owner_name: str = ""
    owner_type: str = ""
    severity: Literal["error", "warning"] = "error"

    def __post_init__(self) -> None:
        # owner/path values can originate from a draft or historical payload.
        # Normalize them once here so management responses, inference adapters,
        # DOM rendering, and diagnostics all consume the same safe issue.
        for field_name in (
            "owner_id",
            "owner_name",
            "owner_type",
            "path",
            "message",
        ):
            object.__setattr__(
                self,
                field_name,
                _safe_report_text(getattr(self, field_name)),
            )
        object.__setattr__(self, "message_key", normalize_message_key(self.message_key))
        object.__setattr__(
            self,
            "message_args",
            normalize_message_args(self.message_args),
        )

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "scope": self.scope,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "path": self.path,
            "message": self.message,
            "message_key": self.message_key,
            "message_args": dict(self.message_args),
            "severity": self.severity,
        }
        if self.owner_type:
            payload["owner_type"] = self.owner_type
        return payload


@dataclass(frozen=True, slots=True)
class ValidationReport:
    stage: str
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "stage": self.stage,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def validation_failure_detail(report: ValidationReport) -> dict[str, object]:
    return {
        "code": "configuration_validation_failed",
        "message": "The configuration contains validation issues.",
        "message_key": "validation.failure.configuration",
        "message_args": {},
        "validation": report.as_dict(),
    }
