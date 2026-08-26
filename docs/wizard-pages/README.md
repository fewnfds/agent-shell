# 组件说明

本目录是配置编辑页的字段索引：前 13 项是 Agent-side Component catalog，其中 Skill Component 只制作独立包；后 4 项是 Workflow-owned 组件。创建与装配见[能力说明](../user-guide/capabilities.md)和[Workflow 配置](../user-guide/configuration-workflow.md)，总体 identity 与引用边界见[Agent Shell 系统契约](../../.docs/architecture/agent-shell-system-contract.md)。

| 所属 / 顺序 | 页面 | 类型 |
| --- | --- | --- |
| Agent / 1 | [Model Connection 与 Model Requirement](model-config.md) | `model-requirement`（绑定实例 Model Connection） |
| Agent / 2 | [System Prompt](system-prompt-config.md) | `system-prompt` |
| Agent / 3 | [Filesystem Backend](filesystem-config.md) | `filesystem` |
| Agent / 4 | [Filesystem Tools](filesystem-tools-config.md) | `filesystem-tools` |
| Agent / 5 | [Todo List](todo-list-config.md) | `todo-list` |
| Agent / 6 | [Custom Tool](custom-tool-config.md) | `custom-tool` |
| Agent / 7 | [Skill 独立包](skill-config.md) | `skill` |
| Agent / 8 | [Custom Middleware](custom-middleware-config.md) | `custom-middleware` |
| Agent / 9 | [Agent Event Output](agent-event-output-config.md) | `agent-event-output` |
| Agent / 10 | [Exception Retry](exception-retry-config.md) | `exception-retry` |
| Agent / 11 | [Subagent Delegation](subagent-config.md) | `subagent` |
| Agent / 12 | [Summarization](summarization-config.md) | `summarization` |
| Agent / 13 | [Prompt Caching](prompt-caching-config.md) | `prompt-caching` |
| Workflow | [Checkpointer](checkpointer-config.md) | `checkpointer` |
| Workflow | [Workflow Event Output](workflow-event-output-config.md) | `workflow-event-output` |
| Workflow | [Command Node](command-config.md) | `command` |
| Workflow | [Task Dispatcher](task-dispatcher-config.md) | `task-dispatcher` |

前 13 行是 Agent-side Component 的固定 catalog order，末 4 行是 Workflow 组件，不参与该 order。`agent_selectable=false` 的 Skill Component 不出现在 Main Agent 或 Subagent 的 capability picker。

模型要求、Filesystem Backend、Filesystem Tools 和 Agent Event Output 是 Main Agent 必选组件。前三者在 Subagent 侧必须继承或替换、不可关闭；Agent Event Output 仅属于顶层 Main Agent，Subagent 事件复用所属 Main Agent 的输出组件，不单独覆写。模型连接在实例“模型”页面维护并通过模型映射绑定。

Filesystem Backend 在 CompositeBackend 与 LocalShellBackend 中二选一。CompositeBackend 的来源各自保存权限，并可引用一个 Skill 独立包；LocalShellBackend 只保存一个真实工作区。Skill Component 只制作独立包，不由 Agent 直接选择。Subagent 分别继承或替换 Backend 与 Tools；Skill 包引用随 CompositeBackend 一起生效。Workflow 不拥有 Filesystem。

其余 Agent capability 按需通过 `capability_refs` 引用；Custom Tool 与 Custom Middleware 分别使用独立有序的 `tool_refs` 与 `middleware_refs`，不参与 capability 的 inherit/replace/disabled。Checkpointer 与 Workflow Event Output 分别通过 Workflow metadata 的 `checkpointer_id` 与 `workflow_event_output_id` 绑定；Command Node 与 Task Dispatcher 由 canvas Node 的配置引用，branch key 与 dispatch key 由对应 Edge 声明。

Component、Main Agent、Subagent 与 Workflow 共用全局 UUID4 identity，跨类型不得复用；名称按各自作用域校验，Workflow name 保留大小写敏感语义并作为公开 model ID。组件编辑页提供草稿校验、新建、保存、复制和删除；Model Connection 在【模型】页面独立维护并通过模型映射绑定，配置库提供通用列表与 Repository 操作。
