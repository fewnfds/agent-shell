from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


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
    caller_run_id: str = ""
    operation_id: str = ""

    @property
    def graph_kind(self) -> Literal["workflow"]:
        return "workflow"

    @property
    def subject_id(self) -> str:
        return self.workflow_id

    @property
    def subject_name(self) -> str:
        return self.workflow_name


@dataclass(frozen=True, slots=True)
class AgentRunIdentity:
    """Shell-owned identity for one Main Agent root Run."""

    request_id: str
    lifecycle_id: str
    run_id: str
    main_agent_id: str
    main_agent_name: str
    thread_id: str = ""
    assistant_id: str = ""
    caller_run_id: str = ""
    operation_id: str = ""

    @property
    def graph_kind(self) -> Literal["agent"]:
        return "agent"

    @property
    def subject_id(self) -> str:
        return self.main_agent_id

    @property
    def subject_name(self) -> str:
        return self.main_agent_name


__all__ = ["AgentRunIdentity", "WorkflowRunIdentity"]
