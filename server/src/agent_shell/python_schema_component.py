from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    field_validator,
)

from agent_shell.configuration.identity import ConfigurationName


class PythonSchemaBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: ConfigurationName
    source: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1),
    ]

    @field_validator("source")
    @classmethod
    def require_python_source(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Python Schema source cannot be empty.")
        return value


class BlockReader(Protocol):
    def get_block_internal(
        self,
        block_type: str,
        block_id: str,
    ) -> dict[str, Any] | None: ...


class PythonSchemaReferenceError(ValueError):
    """The selected Python Schema Component is missing or invalid."""


def python_schema_source(record: Mapping[str, Any]) -> str:
    try:
        return PythonSchemaBlock.model_validate(
            {key: value for key, value in record.items() if key != "id"}
        ).source
    except ValidationError as exc:
        raise PythonSchemaReferenceError(
            "The selected Python Schema Component is invalid."
        ) from exc


def resolve_python_schema_source(
    blocks: BlockReader | None,
    component_id: str | None,
) -> str | None:
    if component_id is None:
        return None
    record = (
        blocks.get_block_internal("python-schema", component_id)
        if blocks is not None
        else None
    )
    if record is None:
        raise PythonSchemaReferenceError(
            f"The selected Python Schema Component {component_id!r} does not exist."
        )
    return python_schema_source(record)


__all__ = [
    "PythonSchemaBlock",
    "PythonSchemaReferenceError",
    "python_schema_source",
    "resolve_python_schema_source",
]
