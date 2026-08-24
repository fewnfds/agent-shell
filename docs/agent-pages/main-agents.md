# Main Agent

Main Agent 是完整、可复用的 Deep Agents assembly。Workflow canvas 中的 Agent Node 通过 `main_agent_id` 引用完整 Main Agent assembly，同一 Main Agent 可以被多个 Node 重复引用；OpenAI `model` 对应 enabled parent Workflow name。

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

`model-requirement` 与 `agent-event-output` 必选，其他 capability 可选。模型要求只描述所需能力，具体模型连接由【模型 / 模型映射】绑定。Main Agent 可选择自己的 configured Filesystem；未选择时自动使用空 StateBackend 与 `read_file` 组成的 minimal Filesystem。Main Agent 也可选择 `filesystem-permissions`；后者同时定义路径权限和文件 tool override。

Todo List、Summarization 与 Prompt Caching 通过 `capability_refs` 独立选择，并分别物化为 official Middleware；未选择时使用同名无行为 replacement，使最终 stack 保持显式。Custom Tool 通过有序 `tool_refs` 装配，Custom Middleware 通过有序 `middleware_refs` 装配；每个列表内 ID 唯一，每个引用对应一份独立配置。Agent 生命周期使用 LangChain Middleware hook。

`capability_refs` 引用 `type=subagent` 的委派组件且 `subagents` 至少包含一个有效实体时，Main Agent 获得 Deep Agents 官方 `task` 工具。当前委派结构为一层同步 `Main -> Subagent`，用于 Agent Node 内部委派；外层 Workflow 单独定义运行拓扑。
