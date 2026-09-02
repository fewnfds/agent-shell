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
    workflow_run_id: str
    workflow_id: str
    workflow_name: str
    workflow_role: str = ""
    checkpoint_thread_id: str | None = None
    parent_workflow_run_id: str = ""
    background_task_id: str = ""
    run_depth: int = 0


__all__ = ["WorkflowRunIdentity"]
