# 待办计划

选择该组件会构造 LangChain `TodoListMiddleware`：

```json
{
  "name": "复杂任务计划",
  "system_prompt_override": null,
  "tool_description_override": null
}
```

两个 override 各自为 `null` 时使用当前 LangChain 版本的默认文本；非空字符串完整覆写对应文本，每个字段最多 100,000 字符。编辑器默认显示当前默认文本，未修改时保存为 `null`，也可以用“还原默认文本”撤销覆写。

选择该组件后，Middleware 向模型提供 `write_todos`。每次调用提交包含 `content` 与 `pending|in_progress|completed` 的完整列表并全量替换当前 todos；未选择组件时不提供该工具。

todos 保存在当前请求的 Agent state 中，不写入 `data/` 或 Workflow Lifecycle 持久化，请求结束即消失。Main Agent 未选择该 capability，或 Subagent 显式保存 `disabled` 时，运行时使用同名无行为 middleware 阻止 Deep Agents 默认 Todo 回填；Subagent 也可以继承或替换配置。
