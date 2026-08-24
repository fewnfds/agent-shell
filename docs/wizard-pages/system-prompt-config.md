# System Prompt

类型为 `system-prompt`，是可选能力；Main Agent 未选择时不向 `create_deep_agent` 传递基础 system prompt，使用框架默认行为。

```json
{"name": "Concise assistant", "system_prompt": "Be concise."}
```

`name` 去首尾空白后必须为 1 至 120 个字符，并在同一类型内大小写不敏感唯一；未知字段会被 `extra=forbid` 拒绝。`system_prompt` 去首尾空白后必须为 1 至 200,000 个字符。Main Agent 选择后作为 `create_deep_agent(system_prompt=...)` 的基础提示；Subagent 未覆写时继承，显式 `replace` 使用另一配置，`disabled` 使用空基础提示。Filesystem、Skill 和 Custom Middleware 仍可在各自 hook 阶段追加或调整有效 system message。
