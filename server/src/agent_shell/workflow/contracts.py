from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_shell.command import BranchKey
from agent_shell.task_dispatcher import DispatchKey
from agent_shell.workflow_identifiers import NodeId


WORKFLOW_SCHEMA_VERSION = 1
WORKFLOW_STATE_CONTRACT = "agent-shell.workflow.agent-invocations.v1"

NodeType = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]*$"),
]
HandleId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]*$"),
]


class WorkflowNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NodeId
    type: NodeType
    type_version: Annotated[int, Field(ge=1)] = 1
    config: dict[str, JsonValue] = Field(default_factory=dict)


class WorkflowEdgeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NodeId
    source: NodeId
    source_handle: HandleId
    target: NodeId
    target_handle: HandleId
    branch_key: BranchKey | None = None
    dispatch_key: DispatchKey | None = None


class WorkflowGraphDefinitionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = WORKFLOW_SCHEMA_VERSION
    state_contract: Literal["agent-shell.workflow.agent-invocations.v1"] = (
        WORKFLOW_STATE_CONTRACT
    )
    nodes: list[WorkflowNodeV1] = Field(default_factory=list)
    edges: list[WorkflowEdgeV1] = Field(default_factory=list)


class WorkflowNodePositionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
    y: Annotated[float, Field(ge=-1_000_000, le=1_000_000)]


class WorkflowViewportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: Annotated[float, Field(ge=-1_000_000, le=1_000_000)] = 0
    y: Annotated[float, Field(ge=-1_000_000, le=1_000_000)] = 0
    zoom: Annotated[float, Field(ge=0.05, le=4)] = 1


class WorkflowLayoutV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: dict[NodeId, WorkflowNodePositionV1] = Field(default_factory=dict)
    viewport: WorkflowViewportV1 = Field(default_factory=WorkflowViewportV1)


class WorkflowGraphDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: WorkflowGraphDefinitionV1
    layout: WorkflowLayoutV1 = Field(default_factory=WorkflowLayoutV1)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_definition_payload(
    definition: WorkflowGraphDefinitionV1,
) -> dict[str, object]:
    payload = definition.model_dump(mode="json")
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["id"])
    payload["edges"] = sorted(payload["edges"], key=lambda item: item["id"])
    return payload


def canonical_workflow_definition_json(
    definition: WorkflowGraphDefinitionV1,
) -> str:
    return _canonical_json(_canonical_definition_payload(definition))


def canonical_workflow_document_json(document: WorkflowGraphDocumentV1) -> str:
    return _canonical_json(
        {
            "definition": _canonical_definition_payload(document.definition),
            "layout": document.layout.model_dump(mode="json"),
        }
    )


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def workflow_document_sha256(document: WorkflowGraphDocumentV1) -> str:
    return _sha256_text(canonical_workflow_document_json(document))


def workflow_executable_sha256(definition: WorkflowGraphDefinitionV1) -> str:
    return _sha256_text(canonical_workflow_definition_json(definition))


__all__ = [
    "WORKFLOW_SCHEMA_VERSION",
    "WORKFLOW_STATE_CONTRACT",
    "NodeId",
    "WorkflowEdgeV1",
    "WorkflowGraphDefinitionV1",
    "WorkflowGraphDocumentV1",
    "WorkflowLayoutV1",
    "WorkflowNodePositionV1",
    "WorkflowNodeV1",
    "WorkflowViewportV1",
    "canonical_workflow_definition_json",
    "canonical_workflow_document_json",
    "workflow_document_sha256",
    "workflow_executable_sha256",
]
