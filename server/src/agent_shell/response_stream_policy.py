from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ResponseStreamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idle_timeout_seconds: Annotated[float, Field(gt=0)] = 2
    max_batch_kb: Annotated[float, Field(gt=0)] = 64
    send_interval_seconds: Annotated[float, Field(ge=0)] = 0.05

__all__ = [
    "ResponseStreamPolicy",
]
