from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from agent_shell.python_packages.contracts import PythonPackageReference


class WorkflowEventOutputBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: Annotated[str, Field(min_length=1, max_length=120)]
    python_package: PythonPackageReference


__all__ = [
    "WorkflowEventOutputBlock",
]
