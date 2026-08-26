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
    "tool_refs": [
      {"tool_id": "custom-tool-uuid"}
    ],
    "middleware_refs": [
      {"middleware_id": "middleware-uuid"}
    ]
  }
}
```

对允许覆写的 capability，未保存 override 表示 `inherit`，即继承 Main Agent 的最终选择；持久化的 `mode` 只有 `replace` 和 `disabled`。required 且可继承的 `model-requirement`、`filesystem` 和 `filesystem-tools` 不能关闭。委派能力 `subagent` 和 Agent Event Output `agent-event-output` 是 `top-level-only`，只属于 Main Agent。Skill 不单独覆写；CompositeBackend 的 `skill_package_id` 随 Backend 一起继承或替换。完整策略见[能力配置](../user-guide/capabilities.md)。

`tool_refs` 和 `middleware_refs` 是 Subagent 自己的有序列表，不继承 Main Agent，也不使用 capability override。Filesystem Backend 与 Filesystem Tools 未覆写时分别继承，显式替换时使用该 Subagent 的最终组合。

`component_name` 是配置显示名；`name` 是模型可见 routing name，必须匹配 `^[A-Za-z_][A-Za-z0-9_-]*$`，并在同一 Main Agent 的 direct children 中按大小写不敏感方式保持唯一。Subagent contract 没有 `settings.subagents` 字段，因此不能再引用 child。运行时将每个 direct child 机械投影为 Deep Agents 官方 dictionary-based `SubAgent` 配置；Shell 不编译第二套 child graph，也不提供循环引用。

每份 Custom Middleware 配置只产生一个官方 `AgentMiddleware`。Subagent 默认看到 Deep Agents delegated state；需要处理消息时在自己的 `before_agent`/`abefore_agent` 中返回 state update。装配基线见[Deep Agents 迁移边界](../deep-agents-migration.md)。
