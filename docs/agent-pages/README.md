# Agent 配置

- [Main Agent](main-agents.md)：选择组件，作为 Workflow 的 Agent 节点装配。
- [Subagent](subagents.md)：定义可复用的同步子代理实体和能力策略；只允许 Main Agent 直接引用。
- [词库](terminology.md)：管理台常用中英文名称。

Main Agent 通过 UUID 引用组件和直接 Subagent 实体；Subagent settings 只保存能力覆写，不引用下级实体。模型要求与 Agent 事件输出是 Main Agent 必选项；Subagent 必须保留一个有效模型要求，Agent 事件输出只属于顶层 Main Agent；Filesystem 可继承、自选或回到最小配置，文件系统权限可继承、替换或关闭；运行时只共享 Deep Agents 官方 StateBackend 文件状态。
