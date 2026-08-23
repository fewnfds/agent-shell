# Main Agent

Main Agent 是完整、可复用的 Deep Agents 装配。它不直接映射为 OpenAI `model`；Workflow 画布的 Agent node 通过 `main_agent_id` 引用完整 Main Agent 装配，同一 Main Agent 可以被多个 Node 重复引用。

每条 Main Agent 记录保存：

```json
{
  "name": "Research coordinator",
  "capability_refs": [
    {"type": "model-requirement", "block_id": "model-requirement-uuid"},
    {"type": "filesystem", "block_id": "filesystem-uuid"},
    {"type": "agent-event-output", "block_id": "output-uuid"}
  ],
  "tool_refs": [
    {"tool_id": "custom-tool-uuid"}
  ],
  "middleware_refs": [
    {"middleware_id": "middleware-uuid-a"},
    {"middleware_id": "middleware-uuid-b"}
  ],
  "subagents": [
    {"subagent_id": "subagent-uuid"}
  ]
}
```

`model-requirement` 与 `agent-event-output` 必选，其他 capability 可选。模型要求只描述所需能力，具体模型连接由【模型 / 模型映射】绑定。Main Agent 可选择自己的项目 Filesystem；未选择时自动使用空 StateBackend 与 `read_file` 组成的最小 Filesystem。Main Agent 也可选择 `filesystem-permissions`；后者同时定义路径权限和文件 tool override。

Todo List、Summarization 与 Prompt Caching 通过 `capability_refs` 独立选择，并分别物化为官方 Middleware；未选择时使用同名无行为 replacement，阻止 Deep Agents 默认 stack 回填。Custom Tool 和 Custom Middleware 不属于 `capability_refs`，分别通过有序的 `tool_refs` 和 `middleware_refs` 装配；每个列表内不得重复 ID，每个引用对应一份独立配置。没有 Agent 外的 prepare、周期循环或结束 Hook。

Main Agent 只有在 `capability_refs` 引用 `type=subagent` 的委派组件，并且 `subagents` 至少包含一个有效 Subagent 实体时才获得 Deep Agents 官方 `task` 工具；只填写实体引用而未选择组件时不会注入 `task`。
当前只支持一层同步 `Main -> Subagent`；这是 Agent 节点内部的官方委派能力，不决定外层 Workflow 拓扑。未来 AsyncSubAgent 通过新增官方装配类型接入，不改变 Workflow 与 Main Agent 的解耦边界。
