# Model Call Limit

`model-call-limit` 保存一条 LangChain `ModelCallLimitMiddleware` 配置。Main Agent 引用该组件时装配 middleware；Subagent 默认继承，也可以替换或关闭。没有引用时不装配模型调用限制。

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `name` | string | 当前 Repository 内该组件类型的唯一配置名。 |
| `run_limit` | integer \| null | 单次 Agent invocation 允许的模型调用数；正整数。每个新 Run 或同步 Subagent 调用重新计数。 |
| `thread_limit` | integer \| null | Main Agent 在同一持久 Thread 中累计允许的模型调用数；正整数，依赖 checkpointer。同步 isolated Subagent 每次 `task` 调用重新计数。 |
| `exit_behavior` | `end` \| `error` | 达限行为；默认 `end`。 |

`run_limit` 与 `thread_limit` 至少填写一个。Agent Shell 不提供隐式次数；组件未被引用时也没有默认限制。

`exit_behavior=end` 让 middleware 写入达限 AI message 并结束当前 Agent；`error` 抛出 LangChain `ModelCallLimitExceededError`，当前 Run 失败。限制检查发生在下一次模型调用之前，因此已经完成的模型调用与 Tool 结果不会被撤销。

Main Agent 的 `thread_limit` 随同一 Agent Thread 的 checkpoint 跨多个 Run 累计。Workflow Command 创建的新 Main Agent Thread 独立计数；明确续用同一 Thread 时继续累计。同步 isolated Subagent 没有独立 checkpointer，每次 `task` 调用都从新的 child state 开始，因此它的 `thread_limit` 只在本次 `task` 内累计，且 private counter 不并入父 Agent 的模型调用计数。

示例：

```json
{
  "name": "Bounded model calls",
  "run_limit": 20,
  "thread_limit": 100,
  "exit_behavior": "end"
}
```

这项能力和 System Settings 的 `recursion_limit` 相互独立。`recursion_limit` 限制 LangGraph super-step；本组件只计算模型调用。

官方说明：[Model call limit](https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-call-limit)。
