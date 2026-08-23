# 委派能力 (`subagent`)

该组件的类型为 `subagent`，由 `/api/blocks/subagent` 管理。它控制 Main Agent 的 Deep Agents 同步 `task` 委派提示；它与被委派的 [Subagent 实体](../agent-pages/subagents.md) 是两层独立配置：

```json
{
  "name": "同步委派",
  "instruction_override": null,
  "task_description_override": null
}
```

- `null` 保留当前依赖版本的默认行为；编辑器显示默认文本，未修改时仍保存为 `null`；
- `instruction_override` 非 `null` 且非空时，以双换行追加到 Main Agent 的 system prompt；空字符串是合法的显式空覆写；
- `task_description_override` 非 `null` 时完整覆写 `task` 工具说明，必须且只能使用 `{available_agents}` 占位符，不支持 format spec 或 conversion，字面大括号须写为 `{{` 和 `}}`；空字符串因缺少必选占位符而校验失败；
- 每段最多 100,000 字符；
- child 的 `name`、模型可见 `description`、`settings.capability_overrides`、`tool_refs` 和 `middleware_refs` 在 Subagent 实体页面维护；Main Agent 另通过 `subagents[].subagent_id` 引用实体。

Main Agent 的 `capability_refs` 必须引用该组件，并且 `subagents` 至少包含一条有效实体引用，运行时才装配 `task`；`task_description_override` 也只在已编译出有效 Subagent 时生效。每个实体由 Shell 投影为 Deep Agents 官方 dictionary-based SubAgent 并同步执行。该 capability 是 `top-level-only`，Subagent 不能继承、替换或关闭它；Subagent contract 也没有下级实体引用字段。
