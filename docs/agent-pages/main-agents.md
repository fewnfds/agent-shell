# Main Agent

Main Agent 是完整、可复用的 Deep Agents 装配。它不直接映射为 OpenAI `model`；Workflow 画布的 Agent node
通过 `main_agent_id` 引用完整 Main Agent 装配，同一 Main Agent 可以被多个 Node 重复引用。

每条 Main Agent 记录保存：

```json
{
  "name": "Research coordinator",
  "capability_refs": [
    {"type": "model-requirement", "block_id": "model-requirement-uuid"},
    {"type": "filesystem", "block_id": "filesystem-uuid"},
    {"type": "agent-event-output", "block_id": "output-uuid"}
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

`model-requirement` 与 `agent-event-output` 必选，其他 capability 可选。模型要求只描述所需能力，具体模型连接由【模型 / 模型映射】绑定。Main Agent 可选择自己的项目 Filesystem；未选择时自动使用空 StateBackend 与 `read_file` 组成的最小 Filesystem。Main Agent 也可选择
`filesystem-permissions`；后者同时定义路径权限和文件
tool override。Summarization 与 Prompt Caching 是两个可独立选择的 middleware capability。自定义 Middleware 使用独立、
有序的 `middleware_refs`，每个引用对应一个 Middleware 配置；没有 Agent 外的 prepare、周期循环或结束 Hook。

Main Agent 只有选择 Subagent capability 并引用至少一个 Subagent 实体时才获得 Deep Agents 官方 `task` 工具。
当前只支持一层同步 `Main -> Subagent`；这是 Agent 节点内部的官方委派能力，不决定外层 Workflow 拓扑。未来
AsyncSubAgent 通过新增官方装配类型接入，不改变 Workflow 与 Main Agent 的解耦边界。
