# 创建组件

【代理组件】和【工作流组件】提供当前 catalog 声明的可复用配置。组件归属当前 active Configuration Repository，跨 Repository 引用无效。保存组件后，还要由 Workflow、Main Agent 或 Subagent 按各自所有权引用才会参与运行。

| 组件 | 用途 | Main Agent 要求 | Subagent 策略 |
| --- | --- | --- | --- |
| 模型要求 | 名称和能力说明 | 必选 | 继承或替换 |
| 系统提示词 | 基础 system prompt | 可选 | 继承、替换或关闭 |
| 文件系统 | Agent workspace、映射、初始文件和文件工具 | 自选；未选时使用最小 Filesystem | 继承、自选或最小 |
| 文件系统权限 | 路径权限与文件工具、提示词覆写 | 可选 | 继承、替换或关闭 |
| 待办计划 | `write_todos` 与规划提示 | 可选 | 继承、替换或关闭 |
| 自定义工具 | 一个 Python extension 导出一个 LangChain Tool | 通过有序引用装配 | Subagent 独立有序引用 |
| Skill | 从 `data/skills-template/` 选择合法 Template，并复制到 Component 私有包 | 可选 | 继承、替换或关闭 |
| 自定义 Middleware | 定义一个 LangChain Middleware | 通过有序引用装配 | Subagent 独立有序引用 |
| Agent 事件输出 | 用文件化 Python 扩展把 v3 Agent 事件投影为响应文本 | 必选 | 只用于顶层 Main Agent |
| 异常重试 | Provider 或 ModelRetryMiddleware 重试 | 可选 | 继承、替换或关闭 |
| 委派能力 | 同步 Subagent 的提示与 `task` 说明 | 可选 | 只用于顶层 Main Agent |
| 上下文摘要 | `SummarizationMiddleware` 阈值、保留和工具参数截断 | 可选 | 继承、替换或关闭 |
| Prompt 缓存 | Anthropic prompt caching TTL 与最少消息数 | 可选 | 继承、替换或关闭 |
| Workflow 事件输出 | 用文件化 Python 扩展把 Workflow-owned v3 事件投影为响应字符串 | Workflow 可选绑定 | 不属于 Agent capability |
| Command | 读取完整 Workflow State/Context，更新 State 并激活零个、一个或多个具名 Branch Edge | 画布 Node 引用 | 不属于 Agent capability |
| 任务分发 | 从 Workflow State/Context 生成任务，并通过 Dispatch Edge 动态 Send 到 worker | 画布 Node 引用 | 不属于 Agent capability |

组件编辑页从服务端 catalog 取得字段、默认值和资源发现结果。草稿校验与保存校验都以后端 contract 为准；记录使用 UUID 引用，重命名不会断开引用。

Skill Template 允许多层目录；遇到某层的 `SKILL.md` 就把该目录视为完整 Skill 边界，合法或不合法都不再向下递归。合法 Template 以 `GET /api/skills` catalog 返回的规范相对路径显示，坏 Template 只在 catalog 报告且不能被选择。创建 Skill Component 时会复制所选目录到 owner UUID 的私有包，之后 Template 改动不会影响 Component。私有包可由用户或 AI 直接编辑；同名 Add 不覆盖，必须先删除并刷新。私有包问题只在组件页载入或刷新时显示 warning，不阻塞保存或运行。

详细字段见[组件说明](../wizard-pages/README.md)。Agent 组合方式见[装配 Main Agent 与 Subagent](configuration-workflow.md)。

自定义 Middleware 组件保存一个配置独占的 Python 扩展引用，并只返回一个官方 LangChain `AgentMiddleware`。Main Agent 和 Subagent 分别通过有序 `middleware_refs` 装配多个配置。格式、安全边界和依赖管理见[文件化 Python 扩展](middleware-packages.md)。

Custom Tool 组件同样保存一个配置独占的 Python 扩展，但固定由同步 `create_tool()` 返回一个 LangChain `BaseTool`。Main Agent 和 Subagent 分别通过有序 `tool_refs` 装配多个配置；每个配置对应一个 Tool。完整 contract 见[自定义工具](../wizard-pages/custom-tool-config.md)。

Workflow Input Context 是重要的 Agent 上下文约定，但不是 catalog 组件。当前通过普通 Custom Middleware 实现：从 `内置示例-workflow-input-context` 创建独立配置，再由 Main Agent 或 Subagent 的 `middleware_refs` 选择。完整原理和修改位置见[Workflow Input Context](workflow-input-context.md)。

每个画布 Agent wrapper 在 Main Agent graph 成功完成后，把公开返回的完整 reduced messages 以 invocation ID 幂等写入 Lifecycle/Run Store；父 Workflow State 的 `agent_invocations` 只保存身份和 `result_ref`，并按 Node/Dispatcher task 逻辑槽保留最新引用。同步 Subagent 仍由 Deep Agents 官方 Middleware 在 Main Agent 内部调度，不建立隐藏归档 wrapper。
这条父子 State 输出映射不需要额外的结束 Hook 或 Recorder 组件。

Workflow 事件输出也是 Workflow-owned 组件。Workflow 通过 UUID 可选绑定一份配置；配置独占扩展中的同步 `output(event)` 读取稳定 dict，返回类型为字符串。它只控制 Workflow-owned 非 Agent 事件的 OpenAI 响应投影，不改变 checkpoint、Debug、最终 State 或 Agent 自己的 Agent 事件输出。字段和 Python 对象类型见[Workflow 事件输出](../wizard-pages/workflow-event-output-config.md)。

Command 组件保存一个 `workflow-node/command` Python 扩展引用和普通 config。扩展通过同步 `create_command()` 工厂物化 `async command(state, runtime)`；用户在画布 Branch Edge 上直接填写业务分支 key，command 通过 `activate` 返回零个、一个或多个完全匹配的 key，并可通过 `update` 返回 State 局部更新；空列表表示当前路径自然结束，平台不保留任何兜底 key 语义。
完整 package 和返回契约见[Command 节点](../wizard-pages/command-config.md)。

任务分发组件保存一个 `workflow-node/task-dispatcher` Python 扩展引用。同步 `create_dispatcher()` 工厂物化 `async dispatch(state, runtime)`；返回的每个任务包含稳定 `task_id`、匹配画布 Dispatch Edge 的 `dispatch_key` 和 JSON `payload`；任意 Python 对象和非有限数会在 Node 边界被拒绝。Shell 将任务映射为 LangGraph `Send`，目标 Agent 的 State、
目标 Agent 私有 State 的 `workflow_task` 与完成后的 `agent_invocations` 轻量记录都带 task identity。
完整规则和 item list 示例见[任务分发](../wizard-pages/task-dispatcher-config.md)。

这些自定义 Python 都运行在服务进程的受信任边界内，没有 sandbox。Custom Tool、自定义 Middleware、Command Node、Task Dispatcher、
Agent 事件输出和 Workflow 事件输出是六类配置独占的 Python 扩展，并在扩展目录可选的 `requirements.txt` 声明外部包；模板和示例本身不运行也不参与依赖。六类目录与通用依赖边界见[文件化 Python 扩展](middleware-packages.md)，各组件的 factory contract 见对应组件页。
启动器只收集 enabled Workflow 可达扩展的 requirements；修改后需重启 Agent Shell 以重建依赖层。文件化扩展源码在下一次请求重新加载。
