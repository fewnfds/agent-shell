from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from agent_shell.runtime.run_identity import AgentRunIdentity, WorkflowRunIdentity


class EventOutputOriginDict(TypedDict):
    lifecycle_id: str
    graph_kind: Literal["agent", "workflow"] | Literal[""]
    run_id: str
    thread_id: str
    assistant_id: str
    caller_run_id: str
    operation_id: str
    workflow_id: str
    main_agent_id: str
    workflow_node_id: str
    node_invocation_id: str
    agent_profile_id: str
    subagent_profile_id: str


@dataclass(frozen=True, slots=True)
class WorkflowNodeSource:
    """Frozen product identity for one compiled Workflow node."""

    source_type: Literal["agent", "script"]
    workflow_node_id: str
    agent_profile_id: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedEventOrigin:
    """One raw event's Shell identity and private scheduling source."""

    output: EventOutputOriginDict
    namespace: str
    cycle_key: str
    source_type: Literal["agent", "subagent", "script", "non_agent"]
    workflow_node_id: str = ""
    node_invocation_id: str = ""
    agent_profile_id: str = ""
    subagent_profile_id: str = ""

    @property
    def is_public_agent(self) -> bool:
        return self.source_type in {"agent", "subagent"}

    @property
    def is_main_agent(self) -> bool:
        return self.source_type == "agent"

    @property
    def correlation_source(self) -> tuple[str, str, str, str]:
        return (
            self.source_type,
            self.workflow_node_id,
            self.agent_profile_id,
            self.subagent_profile_id,
        )


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
    """Resolve product identity once from a raw v3 ProtocolEvent."""

    def __init__(
        self,
        identity: AgentRunIdentity | WorkflowRunIdentity | None,
        *,
        workflow_sources: Mapping[str, WorkflowNodeSource] | None = None,
        main_agent_names: Sequence[str] = (),
        workflow_agent_names: Mapping[str, str] | None = None,
        workflow_subagent_profile_ids: Mapping[str, Mapping[str, str]] | None = None,
        root_agent_profile_id: str = "",
        root_subagent_profile_ids: Mapping[str, str] | None = None,
    ) -> None:
        self._identity = identity
        self._sources = dict(workflow_sources or {})
        self._main_agent_names = tuple(str(name) for name in main_agent_names if name)
        self._workflow_agent_names = {
            str(node_id): str(name)
            for node_id, name in (workflow_agent_names or {}).items()
        }
        self._workflow_subagent_profile_ids = {
            str(node_id): {
                str(name): str(profile_id)
                for name, profile_id in profiles.items()
            }
            for node_id, profiles in (workflow_subagent_profile_ids or {}).items()
        }
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
        cycle_key = _namespace_scope(namespace)

        metadata = _message_metadata(data) if method == "messages" else {}
        node = str(metadata.get("langgraph_node") or params.get("node") or "")
        workflow_node_id, node_invocation_id = self._workflow_node(parts, node)
        source = self._sources.get(workflow_node_id)
        workflow_agent_name = self._workflow_agent_names.get(workflow_node_id, "")

        active_subagent = self._active_subagent(namespace)
        graph_name = (
            str(lifecycle_data.get("graph_name") or "")
            if lifecycle_data is not None
            else ""
        )
        agent_name = str(metadata.get("lc_agent_name") or "")
        agent_name = (
            agent_name
            or active_subagent
            or graph_name
            or workflow_agent_name
        )

        agent_profile_id = (
            source.agent_profile_id
            if source is not None
            else self._root_agent_profile_id
        )
        profiles = (
            self._workflow_subagent_profile_ids.get(workflow_node_id, {})
            if workflow_node_id
            else self._root_subagent_profile_ids
        )
        subagent_profile_id = (
            profiles.get(agent_name, "")
            if agent_name and agent_name not in self._main_agent_names
            else ""
        )
        if subagent_profile_id:
            source_type: Literal["agent", "subagent", "script", "non_agent"] = (
                "subagent"
            )
        elif source is not None:
            source_type = source.source_type
        elif agent_profile_id:
            source_type = "agent"
        else:
            source_type = "non_agent"

        if lifecycle_data is not None:
            status = str(lifecycle_data.get("event") or "")
            if status == "started" and subagent_profile_id:
                self._active_subagents[cycle_key] = agent_name
            elif status != "started":
                self._active_subagents.pop(cycle_key, None)

        output = self._output_origin(
            workflow_node_id=workflow_node_id,
            node_invocation_id=node_invocation_id,
            agent_profile_id=agent_profile_id,
            subagent_profile_id=subagent_profile_id,
        )
        return ResolvedEventOrigin(
            output=output,
            namespace=namespace,
            cycle_key=cycle_key,
            source_type=source_type,
            workflow_node_id=workflow_node_id,
            node_invocation_id=node_invocation_id,
            agent_profile_id=agent_profile_id,
            subagent_profile_id=subagent_profile_id,
        )

    def run_origin(self) -> EventOutputOriginDict:
        return self._output_origin()

    def close(self) -> None:
        self._active_subagents.clear()

    def _workflow_node(
        self,
        parts: Sequence[str],
        node: str,
    ) -> tuple[str, str]:
        if node in self._sources:
            return node, ""
        for segment in reversed(parts):
            name, separator, invocation_id = segment.partition(":")
            if name in self._sources:
                return name, invocation_id if separator else ""
        return "", ""

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
        workflow_node_id: str = "",
        node_invocation_id: str = "",
        agent_profile_id: str = "",
        subagent_profile_id: str = "",
    ) -> EventOutputOriginDict:
        identity = self._identity
        return {
            "lifecycle_id": identity.lifecycle_id if identity is not None else "",
            "graph_kind": identity.graph_kind if identity is not None else "",
            "run_id": identity.run_id if identity is not None else "",
            "thread_id": identity.thread_id if identity is not None else "",
            "assistant_id": identity.assistant_id if identity is not None else "",
            "caller_run_id": identity.caller_run_id if identity is not None else "",
            "operation_id": identity.operation_id if identity is not None else "",
            "workflow_id": (
                identity.workflow_id
                if isinstance(identity, WorkflowRunIdentity)
                else ""
            ),
            "main_agent_id": (
                identity.main_agent_id
                if isinstance(identity, AgentRunIdentity)
                else agent_profile_id
            ),
            "workflow_node_id": workflow_node_id,
            "node_invocation_id": node_invocation_id,
            "agent_profile_id": agent_profile_id,
            "subagent_profile_id": subagent_profile_id,
        }


__all__ = [
    "EventOutputOriginDict",
    "ResolvedEventOrigin",
    "RunEventOriginResolver",
    "WorkflowNodeSource",
]
