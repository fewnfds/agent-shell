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


__all__ = ["BundleImportError"]
