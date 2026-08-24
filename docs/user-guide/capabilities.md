# 创建组件

【代理组件】和【工作流组件】提供当前 catalog 声明的可复用配置。组件归属当前 active Configuration Repository，跨 Repository 引用无效。保存组件后，还要由 Workflow、Main Agent 或 Subagent 按各自所有权引用才会参与运行。

| 组件 | 用途 | Main Agent 要求 | Subagent 策略 |
| --- | --- | --- | --- |
| 模型要求 | 名称和能力说明 | 必选 | 继承或替换 |
| 系统提示词 | 基础 system prompt | 可选 | 继承、替换或关闭 |
| 文件系统 | Agent workspace、映射、初始文件和文件工具 | 自选；未选时使用 minimal Filesystem | 继承、自选或最小 |
| 文件系统权限 | 路径权限与文件工具、提示词覆写 | 可选 | 继承、替换或关闭 |
| 待办计划 | `write_todos` 与规划提示 | 可选 | 继承、替换或关闭 |
| Custom Tool | 一个 Python extension 导出一个 LangChain Tool | 通过有序引用装配 | Subagent 独立有序引用 |
| Skill | 从 `data/skills-template/` 选择合法 Template，并复制到 Component 私有包 | 可选 | 继承、替换或关闭 |
| Custom Middleware | 定义一个 LangChain Middleware | 通过有序引用装配 | Subagent 独立有序引用 |
| Agent Event Output | 用文件化 Python 扩展把 v3 Agent 事件投影为响应文本 | 必选 | 只用于顶层 Main Agent |
| 异常重试 | Provider 或 ModelRetryMiddleware 重试 | 可选 | 继承、替换或关闭 |
| Subagent Delegation | synchronous Subagent 的提示与 `task` 说明 | 可选 | 只用于 top-level Main Agent |
| 上下文摘要 | `SummarizationMiddleware` 阈值、保留和工具参数截断 | 可选 | 继承、替换或关闭 |
| Prompt 缓存 | Anthropic prompt caching TTL 与最少消息数 | 可选 | 继承、替换或关闭 |
| 检查点保存器（Checkpointer） | 为明确选择它的 Workflow 持久化 LangGraph State 检查点，并配置写入时机 | Workflow metadata 可选绑定 | 不属于 Agent capability |
| Workflow Event Output | 用文件化 Python 扩展把 Workflow-owned v3 事件投影为响应字符串 | Workflow 可选绑定 | 不属于 Agent capability |
| Command | 读取完整 Workflow State/Context，更新 State 并激活零个、一个或多个具名 Branch Edge | canvas Node 引用 | 不属于 Agent capability |
| Task Dispatcher | 从 Workflow State/Context 生成任务，并通过 Dispatch Edge 动态 Send 到 worker | canvas Node 引用 | 不属于 Agent capability |

组件编辑页从服务端 catalog 取得字段、默认值和资源发现结果。草稿校验与保存校验都以后端 contract 为准；记录使用 UUID 引用，重命名不会断开引用。

Skill Template 允许多层目录；遇到某层的 `SKILL.md` 时，该目录成为完整 Skill 边界并结束该分支扫描。`GET /api/skills` catalog 使用规范相对路径列出合法 Template，并报告不符合 contract 的 Template；选择器只显示合法项。创建 Skill Component 时会复制所选目录到 owner UUID 的私有包，Template 与 Component 随后独立维护。私有包可由用户或 AI 直接编辑；同名 Add 保留现有文件，可先删除并刷新。私有包问题在组件页载入或刷新时显示 warning，组件仍可保存和运行。

详细字段见[组件说明](../wizard-pages/README.md)。Agent 组合方式见[装配 Main Agent 与 Subagent](configuration-workflow.md)。

Custom Middleware 组件保存一个配置独占的 Python 扩展引用，并只返回一个官方 LangChain `AgentMiddleware`。Main Agent 和 Subagent 分别通过有序 `middleware_refs` 装配多个配置。格式、安全边界和依赖管理见[文件化 Python 扩展](middleware-packages.md)。

Custom Tool 组件同样保存一个配置独占的 Python 扩展，但固定由同步 `create_tool()` 返回一个 LangChain `BaseTool`。Main Agent 和 Subagent 分别通过有序 `tool_refs` 装配多个配置；每个配置对应一个 Tool。完整 contract 见[Custom Tool](../wizard-pages/custom-tool-config.md)。

Agent Additional Prompt（AAP）是推荐的 Agent 初始提示词注入范式，通过普通 Custom Middleware 实现：从 `内置示例-agent-additional-prompt` 创建独立配置，再由需要它的 Main Agent 或 Subagent 通过 `middleware_refs` 选择。完整原理和修改位置见 [Agent Additional Prompt](agent-additional-prompt.md)。

每个 canvas Agent Node wrapper 在 Main Agent graph 成功完成后，把公开返回的完整 reduced messages 以 invocation ID 幂等写入 Lifecycle/Run Store；parent Workflow State 的 `agent_invocations` 只保存 identity 和 `result_ref`，并按 Node/Dispatcher task 逻辑槽保留最新 reference。synchronous Subagent 仍由 Deep Agents official Middleware 在 Main Agent 内部调度，不建立隐藏的 archive wrapper。
这条 parent/child State 输出映射不需要额外的结束 Hook 或 Recorder 组件。

Workflow Event Output 也是 Workflow-owned 组件。Workflow 通过 UUID 可选绑定一份配置；配置独占扩展中的同步 `output(event)` 读取稳定 dict，返回类型为字符串。它只控制 Workflow-owned non-Agent 事件的 OpenAI 响应投影，不改变 checkpoint、Debug、最终 State 或 Agent 自己的 Agent Event Output。字段和 Python 对象类型见[Workflow Event Output](../wizard-pages/workflow-event-output-config.md)。

检查点保存器也是 Workflow-owned 组件。Workflow 通过可空 `checkpointer_id` 选择一个配置，默认【无】；组件只有 `name` 和 `durability=exit|async|sync`，默认 `async`。选择后，Workflow root 使用官方 `AsyncSqliteSaver`，其 Canvas Agent/Deep Agent subgraph 按 LangGraph 默认继承 saver；parent 与 background child Workflow 分别读取自己的配置。未选择时最终 State、Store、Lifecycle、Run/Event/Model Request History、background Run、Tracing、Diagnostics 和 usage 继续工作，只缺少 Checkpoint State 与 Checkpoint Thread。当前软件不提供 Resume 或灾难恢复入口。字段见[检查点保存器](../wizard-pages/checkpointer-config.md)。

Command 组件保存一个 `workflow-node/command` Python 扩展引用和普通 config。扩展通过同步 `create_command()` 工厂物化 `async command(state, runtime)`；用户在画布 Branch Edge 上直接填写业务分支 key，command 通过 `activate` 返回零个、一个或多个完全匹配的 key，并可通过 `update` 返回 State 局部更新；空列表表示当前路径自然结束，平台不保留任何兜底 key 语义。
完整 package 和返回契约见[Command Node](../wizard-pages/command-config.md)。

Task Dispatcher component 保存一个 `workflow-node/task-dispatcher` Python extension reference。同步 `create_dispatcher()` factory 物化 `async dispatch(state, runtime)`；返回的每个 task 包含稳定 `task_id`、匹配 canvas Dispatch Edge 的 `dispatch_key` 和 JSON `payload`；任意 Python object 和 non-finite number 会在 Node boundary 被拒绝。Shell 将 task 映射为 LangGraph `Send`，target Agent 的 State、
target Agent 私有 State 的 `workflow_task` 与完成后的 `agent_invocations` 轻量记录都带 task identity。
完整规则和 item list 示例见[Task Dispatcher](../wizard-pages/task-dispatcher-config.md)。

这些自定义 Python 都运行在服务进程的受信任边界内，没有 sandbox。Custom Tool、Custom Middleware、Command Node、Task Dispatcher、
Agent Event Output 和 Workflow Event Output 是六类配置独占的 Python 扩展，并在扩展目录可选的 `requirements.txt` 声明外部包；模板和示例本身不运行也不参与依赖。六类目录与通用依赖边界见[文件化 Python 扩展](middleware-packages.md)，各组件的 factory contract 见对应组件页。
启动器只收集 enabled Workflow 可达扩展的 requirements；修改后需重启 Agent Shell 以重建依赖层。文件化扩展源码在下一次请求重新加载。
