from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity


class EventOutputOriginDict(TypedDict):
    """Stable Shell identity passed to one root Graph's Event Output."""

    lifecycle_id: str
    graph_kind: Literal["agent", "workflow"] | Literal[""]
    run_id: str
    thread_id: str
    assistant_id: str
    caller_run_id: str
    operation_id: str
    workflow_id: str
    main_agent_id: str
    agent_profile_id: str
    subagent_profile_id: str


@dataclass(frozen=True, slots=True)
class ResolvedEventOrigin:
    """Root Graph identity plus optional Deep Agents subagent attribution."""

    output: EventOutputOriginDict
    namespace: str
    source_type: Literal["agent", "subagent", "workflow"]
    subagent_profile_id: str = ""

    @property
    def is_public_agent(self) -> bool:
        return self.source_type in {"agent", "subagent"}

    @property
    def is_main_agent(self) -> bool:
        return self.source_type == "agent"


def _namespace_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(part) for part in value if str(part))


def _namespace_text(parts: Sequence[str]) -> str:
    return "/".join(parts) or "root"


def _namespace_scope(value: str) -> str:
    parts = [part for part in value.split("/") if part]
    while parts and parts[-1].partition(":")[0] in {"model", "tools"}:
        parts.pop()
    return "/".join(parts) or "root"


def _message_metadata(data: object) -> Mapping[str, object]:
    if isinstance(data, Mapping):
        metadata = data.get("metadata")
        return metadata if isinstance(metadata, Mapping) else {}
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return {}
    return data[1] if isinstance(data[1], Mapping) else {}


class RunEventOriginResolver:
    """Resolve product identity once from a raw v3 ProtocolEvent.

    Workflow events always retain Workflow root identity. Main Agent events may
    additionally expose a configured synchronous Deep Agents subagent profile;
    this attribution is presentation metadata and never a scheduler identity.
    """

    def __init__(
        self,
        identity: AgentRunIdentity | WorkflowRunIdentity | None,
        *,
        main_agent_names: Sequence[str] = (),
        root_agent_profile_id: str = "",
        root_subagent_profile_ids: Mapping[str, str] | None = None,
    ) -> None:
        self._identity = identity
        self._main_agent_names = tuple(str(name) for name in main_agent_names if name)
        self._root_agent_profile_id = root_agent_profile_id
        self._root_subagent_profile_ids = {
            str(name): str(profile_id)
            for name, profile_id in (root_subagent_profile_ids or {}).items()
        }
        self._active_subagents: dict[str, str] = {}

    def resolve(self, event: Mapping[str, object]) -> ResolvedEventOrigin:
        params = event.get("params")
        params = params if isinstance(params, Mapping) else {}
        data = params.get("data")
        method = str(event.get("method") or "")
        parts = _namespace_parts(params.get("namespace"))
        lifecycle_data = data if method == "lifecycle" and isinstance(data, Mapping) else None
        if lifecycle_data is not None:
            lifecycle_parts = _namespace_parts(lifecycle_data.get("namespace"))
            if lifecycle_parts:
                parts = lifecycle_parts
        namespace = _namespace_text(parts)
        scope = _namespace_scope(namespace)

        identity = self._identity
        is_agent_graph = isinstance(identity, AgentRunIdentity) or bool(
            self._root_agent_profile_id
        )
        subagent_profile_id = ""
        source_type: Literal["agent", "subagent", "workflow"] = "workflow"
        if is_agent_graph:
            metadata = _message_metadata(data) if method == "messages" else {}
            active_subagent = self._active_subagent(namespace)
            graph_name = (
                str(lifecycle_data.get("graph_name") or "")
                if lifecycle_data is not None
                else ""
            )
            agent_name = str(metadata.get("lc_agent_name") or "")
            agent_name = agent_name or active_subagent or graph_name
            if agent_name and agent_name not in self._main_agent_names:
                subagent_profile_id = self._root_subagent_profile_ids.get(agent_name, "")
            source_type = "subagent" if subagent_profile_id else "agent"

            if lifecycle_data is not None:
                status = str(lifecycle_data.get("event") or "")
                if status == "started" and subagent_profile_id:
                    self._active_subagents[scope] = agent_name
                elif status != "started":
                    self._active_subagents.pop(scope, None)

        return ResolvedEventOrigin(
            output=self._output_origin(subagent_profile_id=subagent_profile_id),
            namespace=namespace,
            source_type=source_type,
            subagent_profile_id=subagent_profile_id,
        )

    def run_origin(self) -> EventOutputOriginDict:
        return self._output_origin()

    def close(self) -> None:
        self._active_subagents.clear()

    def _active_subagent(self, namespace: str) -> str:
        scope = _namespace_scope(namespace)
        best: tuple[int, str] | None = None
        for active_scope, name in self._active_subagents.items():
            if scope == active_scope or scope.startswith(active_scope + "/"):
                candidate = (len(active_scope), name)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        return best[1] if best is not None else ""

    def _output_origin(
        self,
        *,
        subagent_profile_id: str = "",
    ) -> EventOutputOriginDict:
        identity = self._identity
        main_agent_id = (
            identity.main_agent_id
            if isinstance(identity, AgentRunIdentity)
            else self._root_agent_profile_id
        )
        return {
            "lifecycle_id": identity.lifecycle_id if identity is not None else "",
            "graph_kind": (
                identity.graph_kind
                if identity is not None
                else "agent"
                if main_agent_id
                else ""
            ),
            "run_id": identity.run_id if identity is not None else "",
            "thread_id": identity.thread_id if identity is not None else "",
            "assistant_id": identity.assistant_id if identity is not None else "",
            "caller_run_id": identity.caller_run_id if identity is not None else "",
            "operation_id": identity.operation_id if identity is not None else "",
            "workflow_id": (
                identity.workflow_id if isinstance(identity, WorkflowRunIdentity) else ""
            ),
            "main_agent_id": main_agent_id,
            # Event Output profile aliases for the root Agent and its configured
            # synchronous subagents. Scheduler identity never depends on them.
            "agent_profile_id": main_agent_id,
            "subagent_profile_id": subagent_profile_id,
        }


__all__ = [
    "EventOutputOriginDict",
    "ResolvedEventOrigin",
    "RunEventOriginResolver",
]
