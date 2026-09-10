# Tool Call Limit

`tool-call-limit` 保存一条 LangChain `ToolCallLimitMiddleware` 配置。Main Agent 引用该组件时装配 middleware；Subagent 默认继承，也可以替换或关闭。没有引用时不装配工具调用限制。

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `name` | string | 当前 Repository 内该组件类型的唯一配置名。 |
| `tool_name` | string \| null | 要限制的最终 model-visible Tool name；留空时统计全部工具。 |
| `run_limit` | integer \| null | 单次 Agent invocation 允许的工具调用数；正整数。每个新 Run 或同步 Subagent 调用重新计数。 |
| `thread_limit` | integer \| null | Main Agent 在同一持久 Thread 中累计允许的工具调用数；正整数，依赖 checkpointer。同步 isolated Subagent 每次 `task` 调用重新计数。 |
| `exit_behavior` | `continue` \| `error` \| `end` | 达限行为；默认 `continue`。 |

`run_limit` 与 `thread_limit` 至少填写一个；两者同时填写时必须满足 `run_limit <= thread_limit`。Agent Shell 每个 Agent 对同类型 capability 最多引用一条，所以当前一个 Agent 只能装配一条 Tool Call Limit policy。

`tool_name=null` 统计该 Agent 的所有工具；填写名称时只统计完全匹配的最终 model-visible Tool name。组件可被不同 Agent 复用，因此保存时不要求该名称已经出现在某个 Agent 的工具列表中。MCP Tool 应填写 namespace 处理后的模型可见名称。

达限行为：

- `continue`：阻止超限调用，为它生成错误 `ToolMessage`，然后让模型继续决定下一步；
- `error`：抛出 LangChain `ToolCallLimitExceededError`，当前 Run 失败；
- `end`：阻止该批次的全部待执行调用，为每个调用补充 `ToolMessage`，再追加说明原因的 AI message 并结束当前 Agent。`tool_name` 可以填写或留空，同一响应包含多个并行调用时同样受支持。

Tool limit 检查模型刚生成的工具调用，并在实际 Tool 执行前阻止超限项。Main Agent 的 `thread_limit` 随同一 Agent Thread 的 checkpoint 跨多个 Run 累计。同步 isolated Subagent 没有独立 checkpointer，每次 `task` 调用都从新的 child state 开始，因此它的 `thread_limit` 只在本次 `task` 内累计，且 private counter 不并入父 Agent 的工具调用计数。

示例：

```json
{
  "name": "Bounded searches",
  "tool_name": "search",
  "run_limit": 5,
  "thread_limit": 20,
  "exit_behavior": "continue"
}
```

这项能力不重试 Tool、不修复 Tool 异常，也不改变 System Settings 的 `recursion_limit`。

官方说明：[Tool call limit](https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-call-limit)。
