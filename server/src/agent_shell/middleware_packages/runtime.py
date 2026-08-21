from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import inspect
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Callable
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware

from agent_shell.python_packages.loader import PythonPackageLoader
from agent_shell.runtime.errors import AgentRuntimeError
from agent_shell.validation.assembly import StaticAssembly


@dataclass(frozen=True, slots=True)
class MiddlewareOwner:
    id: str
    type: str
    name: str
    packages: tuple[tuple[str, dict[str, Any]], ...]


class MiddlewarePackageRuntime:
    """Request-local package loading and official Middleware materialization.

    Middleware package factories may request any named construction values
    supplied by the runtime. During execution, a returned ``AgentMiddleware``
    reads graph state and ``Runtime.context`` through LangChain's official
    hooks.
    """

    def __init__(
        self,
        *,
        request_id: str,
        owners: list[MiddlewareOwner],
        packages_dir: Path,
        runtime_root: Path,
        assembly: StaticAssembly | None = None,
    ) -> None:
        self.request_id = request_id or str(uuid4())
        self._owners = owners
        self._owner_by_id = {owner.id: owner for owner in owners}
        self._assembly = assembly
        self._blocks_by_id: dict[str, dict[str, Any]] = {}
        if assembly is not None:
            for block in assembly.middleware_blocks:
                block_id = block.get("id")
                if block_id is not None:
                    self._blocks_by_id[str(block_id)] = block
            for node in assembly.subagent_nodes.values():
                for block in node.middleware_blocks:
                    block_id = block.get("id")
                    if block_id is not None:
                        self._blocks_by_id[str(block_id)] = block
        self._loader = PythonPackageLoader(
            request_id=self.request_id,
            packages_dir=packages_dir,
            runtime_root=runtime_root,
            family="middleware",
            adapter="agent-middleware",
            factory_name="create_middleware",
            factory_parameters=None,
        )
        self._middleware: dict[str, tuple[AgentMiddleware, ...]] = {}
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
    ) -> "MiddlewarePackageRuntime":
        owners: list[MiddlewareOwner] = []

        def middleware_packages(
            blocks: tuple[dict[str, Any], ...],
        ) -> tuple[tuple[str, dict[str, Any]], ...]:
            result: list[tuple[str, dict[str, Any]]] = []
            for block in blocks:
                package = block.get("python_package")
                if isinstance(package, dict):
                    result.append((str(block.get("id", "")), deepcopy(package)))
            return tuple(result)

        owners.append(
            MiddlewareOwner(
                id=main_agent_id,
                type="main_agent",
                name=str(assembly.main_agent.get("name", "")),
                packages=middleware_packages(assembly.middleware_blocks),
            )
        )
        for edge in assembly.subagents:
            key = str(edge.target_key)
            node = assembly.subagent_nodes[key]
            owners.append(
                MiddlewareOwner(
                    id=node.key,
                    type="subagent",
                    name=node.name,
                    packages=middleware_packages(node.middleware_blocks),
                )
            )
        return cls(
            request_id=request_id,
            owners=owners,
            packages_dir=packages_dir,
            runtime_root=runtime_root,
            assembly=assembly,
        )

    @staticmethod
    def _call_factory(
        factory: Callable[..., Any],
        available: Mapping[str, Any],
    ) -> Any:
        """Call a package factory with any named values it requests.

        Middleware package factories are intentionally not constrained to a
        fixed signature. A package may request a subset of the available
        values by name or accept the complete mapping with ``**kwargs``.
        """

        signature = inspect.signature(factory)
        positional: list[Any] = []
        keyword: dict[str, Any] = {}
        accepts_var_keyword = False
        for parameter in signature.parameters.values():
            if parameter.kind is parameter.VAR_KEYWORD:
                accepts_var_keyword = True
                continue
            if parameter.kind is parameter.VAR_POSITIONAL:
                continue
            if parameter.name in available:
                if parameter.kind is parameter.POSITIONAL_ONLY:
                    positional.append(available[parameter.name])
                else:
                    keyword[parameter.name] = available[parameter.name]
                continue
            if parameter.default is parameter.empty:
                raise TypeError(
                    f"Middleware factory requires unavailable argument {parameter.name!r}."
                )
        if accepts_var_keyword:
            for name, value in available.items():
                keyword.setdefault(name, value)
        return factory(*positional, **keyword)

    def middleware_for(
        self,
        owner_id: str,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[AgentMiddleware, ...]:
        cached = self._middleware.get(owner_id)
        if cached is not None:
            return cached
        owner = self._owner_by_id[owner_id]
        if not owner.packages:
            result: tuple[AgentMiddleware, ...] = ()
            self._middleware[owner_id] = result
            return result
        values: list[AgentMiddleware] = []
        for index, (package_owner_id, package) in enumerate(owner.packages):
            folder = str(package["folder"])
            factory, metadata, _package_dir = self._loader.entrypoint(
                owner.id,
                "middleware",
                index,
                folder,
                package_owner_id=package_owner_id,
            )
            try:
                agent = {
                    "id": owner.id,
                    "type": owner.type,
                    "name": owner.name,
                    "package_id": metadata["id"],
                }
                factory_context: dict[str, Any] = {
                    "agent": agent,
                    "owner": agent,
                    "package": deepcopy(package),
                    "package_id": metadata["id"],
                    "request_id": self.request_id,
                }
                block = self._blocks_by_id.get(package_owner_id)
                if block is not None:
                    factory_context["block"] = deepcopy(block)
                if self._assembly is not None:
                    factory_context["assembly"] = self._assembly
                if context is not None:
                    factory_context.update(context)
                produced = self._call_factory(
                    factory,
                    factory_context,
                )
            except Exception as exc:
                raise AgentRuntimeError(
                    "middleware_package_materialization_failed",
                    f"Middleware package {folder!r} could not create Middleware.",
                    status_code=422,
                ) from exc
            if not isinstance(produced, AgentMiddleware):
                raise AgentRuntimeError(
                    "middleware_package_result_invalid",
                    f"Middleware package {folder!r} must return one AgentMiddleware instance.",
                    status_code=422,
                )
            values.append(produced)
        for item in values:
            middleware_type = type(item)
            for sync_name, async_name in (
                ("before_agent", "abefore_agent"),
                ("before_model", "abefore_model"),
                ("after_model", "aafter_model"),
                ("after_agent", "aafter_agent"),
                ("wrap_model_call", "awrap_model_call"),
                ("wrap_tool_call", "awrap_tool_call"),
            ):
                if (
                    getattr(middleware_type, sync_name)
                    is not getattr(AgentMiddleware, sync_name)
                    and getattr(middleware_type, async_name)
                    is getattr(AgentMiddleware, async_name)
                ):
                    raise AgentRuntimeError(
                        "middleware_package_async_hook_required",
                        (
                            f"Middleware package {folder!r} implements "
                            f"{sync_name} without {async_name}."
                        ),
                        status_code=422,
                    )
        result = tuple(values)
        self._middleware[owner_id] = result
        return result

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._loader.close()


__all__ = ["MiddlewareOwner", "MiddlewarePackageRuntime"]
