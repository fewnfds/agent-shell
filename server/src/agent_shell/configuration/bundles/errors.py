from __future__ import annotations


class BundleImportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        issues: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(message)
        self.issues = issues or []


def bundle_issue(
    code: str,
    message: str,
    *,
    message_args: dict[str, object] | None = None,
    **fields: object,
) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "message_key": f"configurationBundle.issues.{code}",
        "message_args": message_args or {},
        **fields,
    }


__all__ = ["BundleImportError", "bundle_issue"]
