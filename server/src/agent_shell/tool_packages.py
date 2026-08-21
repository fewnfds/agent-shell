from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain_core.tools import BaseTool

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.python_packages.packages import (
    resolve_python_package,
    scan_python_package,
)
from agent_shell.runtime.errors import AgentRuntimeError

if TYPE_CHECKING:
    from agent_shell.validation.assembly import StaticAssembly


_FAMILY = "tool"
_ADAPTER = "agent-tool"
_FACTORY = "create_tool"
_PARAMETERS: tuple[str, ...] = ()


def scan_tool_package(
    folder: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    return scan_python_package(
        folder,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=_ADAPTER,
        factory_name=_FACTORY,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


def resolve_tool_package(
    folder: str,
    directory: Path,
    *,
    owner_id: str,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], Path] | None:
    return resolve_python_package(
        folder,
        directory,
        owner_id=owner_id,
        family=_FAMILY,
        adapter=_ADAPTER,
        factory_name=_FACTORY,
        factory_parameters=_PARAMETERS,
        runtime_root=runtime_root,
    )


@dataclass(frozen=True, slots=True)
class ToolOwner:
    id: str
    blocks: tuple[dict[str, Any], ...]


class ToolPackageRuntime:
    def __init__(
        self,
        *,
        request_id: str,
        owners: list[ToolOwner],
        packages_dir: Path,
        runtime_root: Path,
    ) -> None:
        self._owners = {owner.id: owner for owner in owners}
        self._loader = PythonPackageLoader(
            request_id=request_id or str(uuid4()),
            packages_dir=packages_dir,
            runtime_root=runtime_root,
            family=_FAMILY,
            adapter=_ADAPTER,
            factory_name=_FACTORY,
            factory_parameters=_PARAMETERS,
        )
        self._tools: dict[str, tuple[BaseTool, ...]] = {}
        self._closed = False

    @classmethod
    def from_assembly(
        cls,
        assembly: StaticAssembly,
        *,
        main_agent_id: str,
        request_id: str,
        packages_dir: Path,
        runtime_root: Path,
    ) -> "ToolPackageRuntime":
        owners = [ToolOwner(main_agent_id, assembly.tool_blocks)]
        owners.extend(
            ToolOwner(node.key, node.tool_blocks)
            for node in assembly.subagent_nodes.values()
        )
        return cls(
            request_id=request_id,
            owners=owners,
            packages_dir=packages_dir,
            runtime_root=runtime_root,
        )

    def tools_for(self, owner_id: str) -> tuple[BaseTool, ...]:
        cached = self._tools.get(owner_id)
        if cached is not None:
            return cached
        owner = self._owners[owner_id]
        result: list[BaseTool] = []
        for index, block in enumerate(owner.blocks):
            reference = block.get("python_package")
            if not isinstance(reference, dict):
                continue
            folder = str(reference.get("folder", ""))
            factory, _metadata, _package_dir = self._loader.entrypoint(
                owner_id,
                "tool",
                index,
                folder,
                package_owner_id=str(block.get("id", "")),
            )
            try:
                produced = factory()
            except Exception as exc:
                raise AgentRuntimeError(
                    "tool_package_materialization_failed",
                    f"Tool package {folder!r} could not create its Tool.",
                    status_code=422,
                ) from exc
            if not isinstance(produced, BaseTool):
                raise AgentRuntimeError(
                    "tool_package_result_invalid",
                    f"Tool package {folder!r} must return one LangChain BaseTool.",
                    status_code=422,
                )
            result.append(produced)
        tools = tuple(result)
        self._tools[owner_id] = tools
        return tools

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()
        self._tools.clear()


__all__ = [
    "ToolPackageRuntime",
    "resolve_tool_package",
    "scan_tool_package",
]
