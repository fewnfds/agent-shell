from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowRunIdentity:
    """Shell-owned identity for one Workflow Run.

    This identity belongs to the outer Lifecycle/Run coordinator. It must not
    be used as LangGraph's execution or callback ``run_id``.
    """

    request_id: str
    lifecycle_id: str
    run_id: str
    workflow_id: str
    workflow_name: str
    thread_id: str = ""
    assistant_id: str = ""
    checkpoint_thread_id: str | None = None
    caller_run_id: str = ""
    operation_id: str = ""


__all__ = ["WorkflowRunIdentity"]
