from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_shell.validation.capability_assembly import FilesystemMode


SubagentNodeKey = str


@dataclass(frozen=True, slots=True)
class ResolvedSubagentEdge:
    target_key: SubagentNodeKey


@dataclass(frozen=True, slots=True)
class ResolvedSubagent:
    key: SubagentNodeKey
    component_name: str
    name: str
    description: str
    references: dict[str, str]
    blocks: dict[str, dict[str, Any]]
    filesystem_mode: FilesystemMode
    tool_blocks: tuple[dict[str, Any], ...] = ()
    middleware_blocks: tuple[dict[str, Any], ...] = ()
    disabled_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class StaticAssembly:
    main_agent: dict[str, Any]
    references: dict[str, str]
    blocks: dict[str, dict[str, Any]]
    filesystem_mode: FilesystemMode
    disabled_capabilities: frozenset[str]
    subagents: tuple[ResolvedSubagentEdge, ...]
    subagent_nodes: dict[SubagentNodeKey, ResolvedSubagent]
    tool_blocks: tuple[dict[str, Any], ...] = ()
    middleware_blocks: tuple[dict[str, Any], ...] = ()
