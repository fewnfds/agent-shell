# Main Agent

Main Agent是完整、可复用的Deep Agents assembly和Agent Server root graph。它可以通过`is_model_entry=true`直接发布为OpenAI-compatible model，也可以由Workflow Command通过`runtime.context.agent_runs`启动独立Thread/Run。

每条 Main Agent 记录保存：

```json
{
  "name": "Research coordinator",
  "is_model_entry": true,
  "checkpoint_mode": "enabled",
  "durability": "async",
  "on_disconnect": "cancel",
  "capability_refs": [
    {"type": "model-requirement", "block_id": "model-requirement-uuid"},
    {"type": "filesystem", "block_id": "filesystem-uuid"},
    {"type": "filesystem-tools", "block_id": "filesystem-tools-uuid"},
    {"type": "agent-event-output", "block_id": "output-uuid"}
  ],
  "tool_refs": [
    {"tool_id": "custom-tool-uuid"}
  ],
  "middleware_refs": [
    {"middleware_id": "middleware-uuid-a"},
    {"middleware_id": "middleware-uuid-b"}
  ],
  "mcp_refs": [
    {
      "requirement_id": "mcp-requirement-uuid",
      "tool_selection": {"mode": "include", "tools": ["search"]}
    }
  ],
  "subagents": [
    {"subagent_id": "subagent-uuid"}
  ]
}
```

`model-requirement`、`filesystem`、`filesystem-tools` 与 `agent-event-output` 必选，其他 Agent-selectable capability 可选。模型要求只描述所需能力，具体模型连接由【模型 / 模型映射】绑定。Filesystem Backend 负责 CompositeBackend 或 LocalShellBackend 及其路径；Filesystem Tools 独立控制文件工具。Skill Component 不进入 `capability_refs`，CompositeBackend 通过自己的 `skill_package_id` 引用 Skill 独立包。

Todo List、Summarization 与 Prompt Caching 通过 `capability_refs` 独立选择，并分别物化为 official Middleware；未选择时使用同名无行为 replacement，使最终 stack 保持显式。Custom Tool 通过有序 `tool_refs` 装配，Custom Middleware 通过有序 `middleware_refs` 装配；MCP Requirement 通过有序 `mcp_refs` 装配，并为每条引用保存 `all|include` 原始 Tool name 选择。每个列表内 ID 唯一。Agent 生命周期使用 LangChain Middleware hook。

`capability_refs`引用`type=subagent`的委派组件且`subagents`至少包含一个有效实体时，Main Agent获得Deep Agents官方`task`工具。当前直接Subagent用于Main Agent内部同步委派；Workflow单独定义确定性控制拓扑。
