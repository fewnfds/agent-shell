# Subagent

Subagent 是 Main Agent 可直接委派的一层独立配置实体：

```json
{
  "component_name": "Research worker",
  "name": "research_worker",
  "description": "Research delegated topics.",
  "settings": {
    "capability_overrides": [
      {"type": "model-requirement", "mode": "replace", "block_id": "model-requirement-uuid"}
    ],
    "middleware_refs": [
      {"middleware_id": "middleware-uuid"}
    ]
  }
}
```

Subagent 对允许的 capability 使用 `inherit`、`replace` 或 `disabled`。未保存的 `inherit` 表示继承 Main Agent
最终选择；必选能力不能关闭。委派 capability 和 output mode 只属于 Main Agent。

Subagent contract 没有 `settings.subagents` 字段，因此不能再引用 child。运行时将每个 direct child 机械投影为
Deep Agents 官方 dictionary-based `SubAgent` 配置；Shell 不编译第二套 child graph，也不提供循环引用。

自定义 Middleware 不继承 Main Agent；Subagent 通过自己的有序 `settings.middleware_refs` 显式装配。每份配置只产生一个官方
`AgentMiddleware`。Subagent 默认看到 Deep Agents delegated state；需要处理消息
时在自己的 `before_agent`/`abefore_agent` 中返回 state update。
