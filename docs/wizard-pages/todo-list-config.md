# 待办计划

选择该组件会构造 LangChain `TodoListMiddleware`：

```json
{
  "name": "复杂任务计划",
  "system_prompt_override": null,
  "tool_description_override": null
}
```

`null` 使用当前依赖版本的默认文本；非空值完整覆写，最多 100,000 字符。Middleware 向模型提供
`write_todos`，每次调用提交包含 `content` 与 `pending|in_progress|completed` 的完整列表。
Todo state 只在当前 API 请求内存在。Subagent 可以继承、替换或关闭。
