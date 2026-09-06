from __future__ import annotations


LIFECYCLE_NAMESPACE_ROOT = "workflow-lifecycle"
LIFECYCLE_INPUT_KEY = "request"


def _namespace(lifecycle_id: str, *parts: str) -> tuple[str, ...]:
    if not lifecycle_id:
        raise ValueError("lifecycle_id must not be empty")
    return (LIFECYCLE_NAMESPACE_ROOT, lifecycle_id, *parts)


def lifecycle_input_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "input")


def lifecycle_invocations_namespace(
    lifecycle_id: str,
    run_id: str,
) -> tuple[str, str, str, str]:
    if not run_id:
        raise ValueError("run_id must not be empty")
    return _namespace(lifecycle_id, "invocations", run_id)


def lifecycle_filesystem_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "filesystem")


def lifecycle_runs_namespace(lifecycle_id: str) -> tuple[str, str, str]:
    return _namespace(lifecycle_id, "runs")


__all__ = [
    "LIFECYCLE_INPUT_KEY",
    "LIFECYCLE_NAMESPACE_ROOT",
    "lifecycle_filesystem_namespace",
    "lifecycle_input_namespace",
    "lifecycle_invocations_namespace",
    "lifecycle_runs_namespace",
]
