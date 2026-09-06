# Async Subagent Middleware

该组件的类型为 `async-subagent`，界面名称为【Async Subagent Middleware / 异步子代理中间件】。它控制 Main Agent 是否装配 Deep Agents 官方 `AsyncSubAgentMiddleware`，并可覆写 Middleware system prompt 与五个官方 task Tool 的 description。

```json
{
  "name": "异步委派",
  "system_prompt_override": null,
  "start_async_task_description_override": null,
  "check_async_task_description_override": null,
  "update_async_task_description_override": null,
  "cancel_async_task_description_override": null,
  "list_async_tasks_description_override": null
}
```

- `null` 保留当前锁定 Deep Agents 版本的默认值；编辑器显示默认文本，未修改时仍保存为 `null`；
- `system_prompt_override` 非 `null` 时交给官方 Middleware，并由官方追加可用 Async Subagent 列表；当前官方默认值为空，编辑器保留空值时保存为 `null`；
- `start_async_task_description_override` 非 `null` 时完整覆写启动工具说明，必须且只能使用 `{available_agents}` 占位符；字面大括号写为 `{{` 和 `}}`；
- 其余四个 description override 不接受动态占位符；
- 覆写只改变模型可见文本，不改变工具名称、参数 schema、返回的 `Command` 或 `async_tasks` State。

Main Agent 必须同时选择该 capability 并至少引用一项有效的 [Async Subagent 配置](../agent-pages/async-subagents.md)，运行时才装配五个工具：`start_async_task`、`check_async_task`、`update_async_task`、`cancel_async_task`和`list_async_tasks`。只有引用而未选择该组件时，引用作为候选配置保存，但不会启用 Middleware；选择组件但没有有效引用时，正式校验失败。

该 capability 是 `top-level-only`，同步或异步子代理都不会继承、替换或关闭它。Async Subagent 配置资源负责模板 Main Agent、代理角色名和说明；本组件只负责 Middleware 是否装配及其模型可见提示文本。
