# Main Agent

Main Agent是由 LangChain `create_agent()` 和显式 middleware assembly 构造的完整、可复用 Agent Server root graph。持久记录以`enabled=false|true`表示草稿或正式；只有正式且`is_model_entry=true`时才发布为OpenAI-compatible model，正式 Main Agent也可以由Workflow Command通过`runtime.context.agent_runs`启动独立Thread/Run。

每条 Main Agent 记录保存：

```json
{
  "name": "Research coordinator",
  "is_model_entry": true,
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

`model-requirement` 与 `agent-event-output` 必选，其他 Agent-selectable capability 可选。模型要求只描述所需能力，具体模型连接由【模型 / 模型映射】绑定。Filesystem Backend 负责 CompositeBackend 或 LocalShellBackend 及其路径；Filesystem Tools 独立控制文件工具。Tools 需要 Backend；Backend 选择 Skill Package 或设置 filesystem system prompt override 时需要 Tools；`execute` 需要 LocalShellBackend。Skill Component 不进入 `capability_refs`，CompositeBackend 通过自己的 `skill_package_id` 引用 Skill 独立包。

Todo List、Exception Retry、Model Call Limit、Tool Call Limit、Summarization 与 Prompt Caching 通过 `capability_refs` 独立选择，并分别物化为 official Middleware；未选择时对应 middleware slot 物理缺席。Custom Tool 通过有序 `tool_refs` 装配，Custom Middleware 通过有序 `middleware_refs` 装配；MCP Requirement 通过有序 `mcp_refs` 装配，并为每条引用保存 `all|include` 原始 Tool name 选择。每个列表内 ID 唯一。Agent 生命周期使用 LangChain Middleware hook。

`capability_refs`引用`type=subagent`的委派组件且`subagents`至少包含一个有效实体时，Main Agent获得Deep Agents官方`task`工具。当前直接Subagent用于Main Agent内部同步委派；Workflow单独定义确定性控制拓扑。

新建、复制、Bundle 导入和普通 `PUT /agent-shell/api/main-agents/{id}` 都保存为草稿。草稿允许保留装配 error，供后续修正；`PUT /agent-shell/api/main-agents/{id}/publish` 只有在完整装配报告没有 error 时才原子写入正式状态，warning 不阻止正式保存，失败不会覆盖当前记录。删除被正式 Main Agent 引用的 Component 或 Subagent 时保留断裂 UUID，并把受影响 Main Agent 降级为草稿，以便现有 Validation Checklist 精确指出缺口。
