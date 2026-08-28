from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


QueueStrategy = Literal["request", "node_invocation"]


class ResponseQueuePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: QueueStrategy = "request"
    idle_timeout_seconds: Annotated[float, Field(ge=0)] = 2
    max_batch_kb: Annotated[float, Field(gt=0)] = 64
    send_interval_seconds: Annotated[float, Field(ge=0)] = 0.05


class ResponseStreamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: ResponseQueuePolicy = Field(default_factory=ResponseQueuePolicy)

__all__ = [
    "QueueStrategy",
    "ResponseQueuePolicy",
    "ResponseStreamPolicy",
]
