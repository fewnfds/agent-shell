# Agent 配置

- [Main Agent](main-agents.md)：选择组件，形成可直接运行或由Command启动的root graph。
- [Subagent](subagents.md)：定义可复用的 synchronous Subagent entity 和 capability policy；只允许 Main Agent 直接引用。
- [词库](terminology.md)：管理台常用中英文名称。

Main Agent 通过 UUID 引用 capability component、有序 `tool_refs`/`middleware_refs` 和 direct Subagent entity。Subagent settings 保存 `capability_overrides`、有序 `tool_refs` 与 `middleware_refs`，不引用下级实体。Model Requirement、Filesystem Backend、Filesystem Tools 与 Agent Event Output 是 Main Agent 必选组件；Subagent 必须保留前三者的 effective 配置，Agent Event Output 只属于 top-level Main Agent。Backend 与 Tools 分别继承或替换；Custom Tool/Middleware 通过独立有序引用装配，不参与 capability override。Workflow 不保存 Filesystem；同一 Workflow Run 内的 synchronous Agent 只共享 Deep Agents 官方 StateBackend 文件状态，同一 Lifecycle 中引用相同 Composite mapped directory 的独立 Run 可复用同一落盘目录。Skill 独立包只由 CompositeBackend 引用，并随 Backend 继承。

完整装配、校验与生效见 [Workflow、Main Agent 与 Subagent](../user-guide/configuration-workflow.md)；字段级索引见 [组件说明](../wizard-pages/README.md)。
