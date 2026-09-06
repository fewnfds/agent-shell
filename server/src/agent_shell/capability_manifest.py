from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


DEFAULT_FILESYSTEM_TOOL_NAMES = (
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
)

FILESYSTEM_TOOL_NAMES = (
    *DEFAULT_FILESYSTEM_TOOL_NAMES[:4],
    "delete",
    *DEFAULT_FILESYSTEM_TOOL_NAMES[4:],
    "execute",
)

ASYNC_SUBAGENT_TOOL_NAMES = (
    "start_async_task",
    "check_async_task",
    "update_async_task",
    "cancel_async_task",
    "list_async_tasks",
)

# Deep Agents installs these middleware slots even when Agent Shell has no
# corresponding capability reference. The runtime uses this catalog to keep
# an explicit "not attached" selection from falling back to those defaults.
DEFAULT_MIDDLEWARE_CAPABILITY_TYPES = frozenset(
    {"todo-list", "summarization", "prompt-caching"}
)


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Small catalog record shared by the API and Vue authoring forms."""

    type: str
    terminology_key: str
    label: str
    order: int
    icon_key: str
    editor_key: str
    subagent_overrideable: bool
    required: bool
    subagent_policy: Literal["inherit", "force-remove", "top-level-only"]
    agent_selectable: bool = True
    tool_names: tuple[str, ...] = ()

    def public_dict(self) -> dict:
        return {
            "type": self.type,
            "terminology_key": self.terminology_key,
            "label": self.label,
            "order": self.order,
            "icon_key": self.icon_key,
            "editor_key": self.editor_key,
            "subagent_overrideable": self.subagent_overrideable,
            "required": self.required,
            "subagent_policy": self.subagent_policy,
            "agent_selectable": self.agent_selectable,
            "tool_names": list(self.tool_names),
        }


CAPABILITY_MANIFESTS = (
    CapabilityManifest(
        "model-requirement", "model-requirement", "模型要求", 1, "bot", "model_requirement",
        subagent_overrideable=True, required=True, subagent_policy="inherit",
    ),
    CapabilityManifest(
        "system-prompt", "system-prompt", "系统提示词",
        2, "message-square", "system_prompt",
        subagent_overrideable=True, required=False, subagent_policy="inherit",
    ),
    CapabilityManifest(
        "filesystem", "file-system", "文件系统后端", 3,
        "folder", "filesystem",
        subagent_overrideable=True, required=True, subagent_policy="inherit",
    ),
    CapabilityManifest(
        "filesystem-tools", "filesystem-tools", "文件系统工具", 4,
        "wrench", "filesystem_tools",
        subagent_overrideable=True, required=True, subagent_policy="inherit",
        tool_names=FILESYSTEM_TOOL_NAMES,
    ),
    CapabilityManifest(
        "todo-list", "todo-list", "待办计划", 5,
        "check", "todo_list",
        subagent_overrideable=True, required=False, subagent_policy="inherit",
        tool_names=("write_todos",),
    ),
    CapabilityManifest(
        "custom-tool", "custom-tool", "自定义工具", 6,
        "wrench", "custom_tool",
        subagent_overrideable=False, required=False, subagent_policy="force-remove",
    ),
    CapabilityManifest(
        "skill", "skill", "Skill 独立包", 7, "sparkles",
        "skill", subagent_overrideable=False, required=False,
        subagent_policy="top-level-only", agent_selectable=False,
    ),
    CapabilityManifest(
        "custom-middleware", "middleware", "自定义中间件", 8,
        "layers", "custom_middleware",
        subagent_overrideable=False, required=False, subagent_policy="force-remove",
    ),
    CapabilityManifest(
        "agent-event-output", "agent-event-output", "Agent 事件输出", 9,
        "braces", "agent_event_output",
        subagent_overrideable=False, required=True, subagent_policy="top-level-only",
    ),
    CapabilityManifest(
        "exception-retry", "exception-retry", "异常重试", 10,
        "arrow-repeat", "exception_retry",
        subagent_overrideable=True, required=False, subagent_policy="inherit",
    ),
    CapabilityManifest(
        "subagent", "delegation", "委派能力", 11,
        "users", "subagent",
        subagent_overrideable=False, required=False, subagent_policy="top-level-only",
    ),
    CapabilityManifest(
        "async-subagent", "async-subagent-middleware", "异步子代理中间件", 12,
        "clock", "async_subagent",
        subagent_overrideable=False, required=False, subagent_policy="top-level-only",
        tool_names=ASYNC_SUBAGENT_TOOL_NAMES,
    ),
    CapabilityManifest(
        "summarization", "summarization", "上下文摘要", 13,
        "file-text", "summarization",
        subagent_overrideable=True, required=False, subagent_policy="inherit",
    ),
    CapabilityManifest(
        "prompt-caching", "prompt-caching", "Prompt 缓存", 14,
        "database", "prompt_caching",
        subagent_overrideable=True, required=False, subagent_policy="inherit",
    ),
)


def validate_capability_manifests(
    manifests: tuple[CapabilityManifest, ...],
    block_models: Mapping[str, object] | None = None,
) -> None:
    types = [manifest.type for manifest in manifests]
    orders = [manifest.order for manifest in manifests]
    if len(types) != len(set(types)):
        raise ValueError("capability manifest types must be unique")
    if len(orders) != len(set(orders)) or orders != sorted(orders):
        raise ValueError("capability manifest orders must be unique and ordered")
    if block_models is not None and set(types) != set(block_models):
        raise ValueError("capability manifests and block models must correspond one-to-one")


validate_capability_manifests(CAPABILITY_MANIFESTS)
CAPABILITY_BY_TYPE = {manifest.type: manifest for manifest in CAPABILITY_MANIFESTS}
PUBLIC_CAPABILITY_MANIFESTS = [manifest.public_dict() for manifest in CAPABILITY_MANIFESTS]
