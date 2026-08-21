# 组件说明

| 顺序 | 页面 | 类型 |
| --- | --- | --- |
| 1 | [模型连接与模型要求](model-config.md) | Model Connection / `model-requirement` |
| 2 | [系统提示词](system-prompt-config.md) | `system-prompt` |
| 3 | [文件系统](filesystem-config.md) | `filesystem` |
| 4 | [文件系统权限](filesystem-permissions-config.md) | `filesystem-permissions` |
| 5 | [待办计划](todo-list-config.md) | `todo-list` |
| 6 | [自定义工具](custom-tool-config.md) | `custom-tool` |
| 7 | [Skill](skill-config.md) | `skill` |
| 8 | [自定义 Middleware](custom-middleware-config.md) | `custom-middleware` |
| 9 | [Agent 事件输出](agent-event-output-config.md) | `agent-event-output` |
| 10 | [异常重试](exception-retry-config.md) | `exception-retry` |
| 11 | [委派能力](subagent-config.md) | `subagent` |
| 12 | [上下文摘要](summarization-config.md) | `summarization` |
| 13 | [Prompt 缓存](prompt-caching-config.md) | `prompt-caching` |
| Workflow | [Workflow 事件输出](workflow-event-output-config.md) | `workflow-event-output` |
| Workflow | [Command 节点](command-config.md) | `command` |
| Workflow | [任务分发](task-dispatcher-config.md) | `task-dispatcher` |

模型要求和 Agent 事件输出是 Main Agent 必选组件；模型连接在实例“模型”页面维护并通过模型映射绑定；Filesystem 由每个 Agent 自选，未选时使用最小 Filesystem；Workflow 事件输出由 Workflow 可选绑定；Command 与任务分发由画布 Node 引用；
Main Agent 显示“最小 / 项目 Filesystem”，Subagent 显示“继承 / 最小 / 项目 Filesystem”。其余 Agent capability 按需引用。
组件使用 UUID 建立引用；名称用于显示。
编辑页提供草稿校验、新建、重置和保存，删除集中在组件库。
