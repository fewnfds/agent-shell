# Async Subagent

Async Subagent（异步子代理）是可复用的配置资源。它选择一个已有 Main Agent 作为模板，并保存模型可见的代理角色名与说明；它不复制模板配置，也不创建第二个 Agent Graph。

每条配置保存：

```json
{
  "component_name": "Background research",
  "main_agent_id": "template-main-agent-uuid",
  "name": "researcher",
  "description": "Research long-running questions in the background."
}
```

`component_name`用于配置库和引用选择，`name`是官方异步任务工具看到的代理角色名。一个 Main Agent 可以有序引用多个 Async Subagent 配置，但同一配置不能重复引用，所有有效角色名按大小写不敏感语义唯一，模板不能指回引用方 Main Agent。

Async Subagent 引用不会自行开启异步能力。引用方 Main Agent 还必须显式选择【Async Subagent / 异步子代理】组件；选择组件但没有引用时保存失败。该组件可设置 Middleware system prompt，并可分别覆盖五个官方工具的 description；空 override 使用当前锁定 Deep Agents 版本的官方默认文本。

每个异步 task 使用模板 Main Agent 的完整 Graph、模型、Tools、Middleware、MCP 和 Filesystem，在独立 Thread/Run 中执行。Thread checkpoint 固定启用，checkpoint 保存时机固定为官方默认`async`；child Run 创建时冻结模板 Main Agent 的【用户断开】策略。父 Agent 仍通过官方`start_async_task`、`check_async_task`、`update_async_task`、`cancel_async_task`和`list_async_tasks`管理 task。

child 进入父 Lifecycle 的运行监控、用户断开处理和 retention，但原始 stream 不直接写入父 response。父 Agent 需要公开 child 结果时，应先通过官方工具读取，再把结果写入自己的回复。
