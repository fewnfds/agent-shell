from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import sys
from types import ModuleType
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError


class GraphSchemaError(ValueError):
    """The configured Python graph schema is missing or invalid."""


@dataclass(frozen=True, slots=True)
class GraphSchema:
    """Compiled Pydantic models declared by one graph resource."""

    source: str
    state_model: type[BaseModel]
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None

    def validate_state(self, value: Mapping[str, Any]) -> None:
        try:
            self.state_model.model_validate(dict(value))
        except ValidationError as exc:
            raise GraphSchemaError(_format_validation_error(exc)) from exc
        except Exception as exc:
            raise GraphSchemaError(
                f"The Python graph schema could not validate State: {exc}"
            ) from exc

    def validate_output(self, value: Mapping[str, Any]) -> None:
        if self.output_model is None:
            return
        output = {
            key: value[key]
            for key in self.output_model.model_fields
            if key in value
        }
        try:
            self.output_model.model_validate(output)
        except ValidationError as exc:
            raise GraphSchemaError(_format_validation_error(exc)) from exc
        except Exception as exc:
            raise GraphSchemaError(
                f"The Python graph schema could not validate Output: {exc}"
            ) from exc


def _format_validation_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    detail = str(first.get("msg", "Invalid value"))
    return f"{location}: {detail}" if location else detail


def _model_fields(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields)


def _require_model(
    module: Mapping[str, Any],
    name: str,
    *,
    required: bool,
) -> type[BaseModel] | None:
    value = module.get(name)
    if value is None:
        if required:
            raise GraphSchemaError(
                f"The Python graph schema must define a Pydantic '{name}' model."
            )
        return None
    if not isinstance(value, type) or not issubclass(value, BaseModel):
        raise GraphSchemaError(
            f"The Python graph schema '{name}' must be a Pydantic BaseModel."
        )
    return value


def _compile_source(
    source: str,
    *,
    require_input: bool,
    require_output: bool,
) -> GraphSchema:
    module_name = f"_agent_shell_graph_schema_{uuid4().hex}"
    module = ModuleType(module_name)
    module.__dict__["__name__"] = module_name
    sys.modules[module_name] = module
    try:
        code = compile(
            source,
            f"<graph-schema:{sha256(source.encode('utf-8')).hexdigest()[:12]}>",
            "exec",
        )
        exec(code, module.__dict__)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise GraphSchemaError(
            f"The Python graph schema could not be loaded: {exc}"
        ) from exc

    try:
        state_model = _require_model(module.__dict__, "State", required=True)
        input_model = _require_model(
            module.__dict__,
            "Input",
            required=require_input,
        )
        output_model = _require_model(
            module.__dict__,
            "Output",
            required=require_output,
        )
        assert state_model is not None
        state_fields = _model_fields(state_model)
        for label, model in (("Input", input_model), ("Output", output_model)):
            if model is None:
                continue
            missing = sorted(_model_fields(model) - state_fields)
            if missing:
                raise GraphSchemaError(
                    f"The '{label}' fields must also exist on 'State': "
                    + ", ".join(missing)
                )
    except GraphSchemaError:
        sys.modules.pop(module_name, None)
        raise
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise GraphSchemaError(
            f"The Python graph schema could not be compiled: {exc}"
        ) from exc

    return GraphSchema(
        source=source,
        state_model=state_model,
        input_model=input_model,
        output_model=output_model,
    )


@lru_cache(maxsize=128)
def _cached_schema(
    source: str,
    require_input: bool,
    require_output: bool,
) -> GraphSchema:
    return _compile_source(
        source,
        require_input=require_input,
        require_output=require_output,
    )


def compile_graph_schema(
    source: str | None,
    *,
    require_input: bool = False,
    require_output: bool = False,
) -> GraphSchema | None:
    """Compile one optional Python Pydantic graph schema."""

    if source is not None and not isinstance(source, str):
        raise GraphSchemaError(
            "The graph schema source must be Python source text."
        )
    if source is None or not source.strip():
        if require_input or require_output:
            raise GraphSchemaError(
                "This graph resource requires a Python Pydantic schema."
            )
        return None
    return _cached_schema(source, require_input, require_output)


__all__ = [
    "GraphSchema",
    "GraphSchemaError",
    "compile_graph_schema",
]
