from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agent_shell.configuration.identity import ConfigurationName
from agent_shell.python_packages.contracts import PythonPackageReference


class WorkflowEventOutputBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ConfigurationName
    python_package: PythonPackageReference


__all__ = [
    "WorkflowEventOutputBlock",
]
