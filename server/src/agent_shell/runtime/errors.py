from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_shell.validation.models import ValidationReport


class AgentRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 500,
        validation_report: ValidationReport | None = None,
    ) -> None:
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.validation_report = validation_report
        super().__init__(code)
