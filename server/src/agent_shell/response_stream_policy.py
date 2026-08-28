from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_shell.workflow_identifiers import NodeId

if TYPE_CHECKING:
    from agent_shell.workflow.contracts import WorkflowGraphDefinitionV1


QueueMode = Literal["fair_turns", "strict_source"]
ContentDelivery = Literal["live", "complete", "activity", "hidden"]
EventDelivery = Literal["complete", "activity", "hidden"]
LifecycleDelivery = Literal["complete", "activity", "hidden"]
ToolDelivery = Literal["paired", "activity", "hidden"]
SourceVisibility = Literal["activity_only", "hidden"]

RESPONSE_STREAM_SOURCE_NODE_TYPES = frozenset(
    {"agent", "command", "task-dispatcher"}
)


class ResponseQueuePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: QueueMode = "fair_turns"
    successor_grace_seconds: Annotated[float, Field(ge=0)] = 2


class LiveWrapper(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = ""
    end: str = ""


class ContentDeliveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: ContentDelivery
    live_wrapper: LiveWrapper = Field(default_factory=LiveWrapper)


class ContentVisibilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: ContentDelivery


class EventDeliveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: EventDelivery


class LifecycleDeliveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: LifecycleDelivery


class ToolDeliveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: ToolDelivery = "paired"


class ResponseActivityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    announce_start: bool = True
    announce_queued: bool = True
    hidden_delta_pulse_seconds: Annotated[float, Field(gt=0)] | None = 15
    quiet_notice_after_seconds: Annotated[float, Field(gt=0)] | None = 30
    quiet_notice_repeat_seconds: Annotated[float, Field(gt=0)] | None = 60


class ResponseSourceOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_node_id: NodeId
    visibility: SourceVisibility


class ResponseStreamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: ResponseQueuePolicy = Field(default_factory=ResponseQueuePolicy)
    assistant_text: ContentDeliveryPolicy = Field(
        default_factory=lambda: ContentDeliveryPolicy(delivery="live")
    )
    reasoning: ContentDeliveryPolicy = Field(
        default_factory=lambda: ContentDeliveryPolicy(
            delivery="live",
            live_wrapper=LiveWrapper(
                start='<details type="agent"><summary>Reasoning</summary>',
                end="</details>\n",
            ),
        )
    )
    subagent_content: ContentVisibilityPolicy = Field(
        default_factory=lambda: ContentVisibilityPolicy(delivery="hidden")
    )
    tools: ToolDeliveryPolicy = Field(default_factory=ToolDeliveryPolicy)
    subagent_lifecycle: LifecycleDeliveryPolicy = Field(
        default_factory=lambda: LifecycleDeliveryPolicy(delivery="activity")
    )
    workflow_custom: EventDeliveryPolicy = Field(
        default_factory=lambda: EventDeliveryPolicy(delivery="complete")
    )
    workflow_lifecycle: LifecycleDeliveryPolicy = Field(
        default_factory=lambda: LifecycleDeliveryPolicy(delivery="activity")
    )
    activity: ResponseActivityPolicy = Field(default_factory=ResponseActivityPolicy)
    source_overrides: list[ResponseSourceOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_source_overrides(self) -> "ResponseStreamPolicy":
        node_ids = [item.workflow_node_id for item in self.source_overrides]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("source_overrides must contain unique workflow_node_id values")
        return self


def default_response_stream_policy() -> dict[str, object]:
    return ResponseStreamPolicy().model_dump(mode="json")


def missing_response_stream_source_ids(
    policy: ResponseStreamPolicy,
    definition: "WorkflowGraphDefinitionV1",
) -> tuple[str, ...]:
    available = {
        node.id
        for node in definition.nodes
        if node.type in RESPONSE_STREAM_SOURCE_NODE_TYPES
    }
    return tuple(
        override.workflow_node_id
        for override in policy.source_overrides
        if override.workflow_node_id not in available
    )


__all__ = [
    "ContentDelivery",
    "ContentDeliveryPolicy",
    "ContentVisibilityPolicy",
    "EventDelivery",
    "EventDeliveryPolicy",
    "LifecycleDelivery",
    "LifecycleDeliveryPolicy",
    "LiveWrapper",
    "QueueMode",
    "RESPONSE_STREAM_SOURCE_NODE_TYPES",
    "ResponseActivityPolicy",
    "ResponseQueuePolicy",
    "ResponseSourceOverride",
    "ResponseStreamPolicy",
    "SourceVisibility",
    "ToolDelivery",
    "ToolDeliveryPolicy",
    "default_response_stream_policy",
    "missing_response_stream_source_ids",
]
