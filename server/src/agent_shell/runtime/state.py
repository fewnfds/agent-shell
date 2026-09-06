from __future__ import annotations

from copy import deepcopy
from functools import cache
from typing import Annotated, Any
from typing_extensions import TypedDict
from typing_extensions import NotRequired

from deepagents import DeepAgentState
from deepagents.middleware.filesystem import FilesystemState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from pydantic import JsonValue, TypeAdapter


def merge_shared_vars(
    current: dict[str, JsonValue] | None,
    update: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    """Merge independent public variable patches across graph branches."""

    return {**(current or {}), **(update or {})}


class WorkflowState(TypedDict):
    """Deterministic control state shared by Workflow Command super-steps."""

    shared_vars: NotRequired[Annotated[dict[str, JsonValue], merge_shared_vars]]


@cache
def _workflow_state_update_adapter() -> TypeAdapter[Any]:
    return TypeAdapter(WorkflowState)


def validate_workflow_state_update(update: dict[str, Any]) -> dict[str, Any]:
    return _workflow_state_update_adapter().validate_python(update)


class AgentShellState(DeepAgentState, FilesystemState):
    """State owned by one Main Agent or synchronous Deep Agents subagent."""


class AgentInitialFilesState(TypedDict):
    """Private marker that prevents virtual source reseeding in one Thread."""

    _agent_shell_initial_files_loaded: NotRequired[
        Annotated[bool, PrivateStateAttr]
    ]


class AgentInitialFilesMiddleware(AgentMiddleware[AgentInitialFilesState]):
    """Seed immutable configured virtual files once in a Main Agent Thread."""

    state_schema = AgentInitialFilesState

    def __init__(self, initial_files: dict[str, Any]) -> None:
        super().__init__()
        self._initial_files = deepcopy(initial_files)

    @property
    def name(self) -> str:
        return "AgentShellInitialFilesMiddleware"

    async def abefore_agent(
        self,
        state: AgentInitialFilesState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        del runtime
        if state.get("_agent_shell_initial_files_loaded"):
            return None
        return {
            "files": deepcopy(self._initial_files),
            "_agent_shell_initial_files_loaded": True,
        }


__all__ = [
    "AgentInitialFilesMiddleware",
    "AgentInitialFilesState",
    "AgentShellState",
    "WorkflowState",
    "merge_shared_vars",
    "validate_workflow_state_update",
]
