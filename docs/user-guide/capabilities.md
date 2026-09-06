# 创建组件

【代理组件】和【工作流组件】提供当前 catalog 声明的可复用配置。组件归属当前 active Configuration Repository，跨 Repository 引用无效。保存组件后，还要由 Workflow、Main Agent 或 Subagent 按各自所有权引用才会参与运行。

| 组件 | 用途 | Main Agent 要求 | Subagent 策略 |
| --- | --- | --- | --- |
| 模型要求 | 名称和能力说明 | 必选 | 继承或替换 |
| 系统提示词 | 基础 system prompt | 可选 | 继承、替换或关闭 |
| 文件系统后端 | CompositeBackend 的映射、来源权限与 Skill 独立包，或 LocalShellBackend 的真实单工作区 | 必选 | 继承或替换 |
| 文件系统工具 | 文件 Tool 可见性、说明与执行参数 | 必选 | 继承或替换 |
| 待办计划 | `write_todos` 与规划提示 | 可选 | 继承、替换或关闭 |
| Custom Tool | 一个 Python extension 导出一个 LangChain Tool | 通过有序引用装配 | Subagent 独立有序引用 |
| Skill | 从 `data/skills-template/` 选择合法 Template，并制作 Skill 独立包 | 由 CompositeBackend 引用 | 随 Filesystem Backend 生效 |
| Custom Middleware | 定义一个 LangChain Middleware | 通过有序引用装配 | Subagent 独立有序引用 |
| Agent Event Output | 用文件化 Python 扩展把 v3 Agent 事件投影为响应文本 | 必选 | 只用于顶层 Main Agent |
| 异常重试 | Provider 或 ModelRetryMiddleware 重试 | 可选 | 继承、替换或关闭 |
| Subagent Delegation | synchronous Subagent 的提示与 `task` 说明 | 可选 | 只用于 top-level Main Agent |
| 上下文摘要 | `SummarizationMiddleware` 阈值、保留和工具参数截断 | 可选 | 继承、替换或关闭 |
| Prompt 缓存 | Anthropic prompt caching TTL 与最少消息数 | 可选 | 继承、替换或关闭 |
| MCP Requirement | 可迁移的 MCP 依赖说明与稳定 namespace；实例 Connection 由 MCP Mapping 绑定 | 通过有序 `mcp_refs` 装配 | Subagent 独立有序引用 |
| Workflow Event Output | 用文件化 Python 扩展把 Workflow-owned v3 事件投影为响应字符串 | Workflow 可选绑定 | 不属于 Agent capability |
| Command | 读取 Workflow State/Context并直接返回官方`Command(update, goto)`；可通过Run facade启动独立Agent/Workflow | canvas Node引用 | 不属于Agent capability |

组件编辑页从服务端 catalog 取得字段、默认值和资源发现结果。草稿校验与保存校验都以后端 contract 为准；记录使用 UUID 引用，重命名不会断开引用。

MCP Requirement 是 Repository resource component，不进入 Agent capability manifest。Main Agent、Subagent 与 Command 各自通过 ordered `mcp_refs` 引用，并选择服务器全部 Tool 或原始 Tool name allowlist；连接、映射、secret 和调用方式见 [MCP 连接、映射与调用](mcp.md)。

Skill Template 允许多层目录；遇到某层的 `SKILL.md` 时，该目录成为完整 Skill 边界并结束该分支扫描。`GET /agent-shell/api/skills` catalog 使用规范相对路径列出合法 Template，并报告不符合 contract 的 Template；选择器只显示合法项。创建 Skill Component 时会复制所选目录到以 Component 配置名称命名、由 Component UUID 拥有的 Skill 独立包，Template 与 Component 随后独立维护。独立包可由用户或 AI 直接编辑；同名 Add 保留现有文件，可先删除并刷新。独立包问题在组件页载入或刷新时显示 warning，组件仍可保存。Agent 不直接选择 Skill Component；CompositeBackend 通过 `skill_package_id` 引用独立包并只读挂载 `/skills/`，LocalShellBackend 不装配 Skill。

详细字段见[组件说明](../wizard-pages/README.md)。Agent 组合方式见[装配 Main Agent 与 Subagent](configuration-workflow.md)。

Custom Middleware 组件保存一个配置独占的 Python 扩展引用，并只返回一个官方 LangChain `AgentMiddleware`。Main Agent 和 Subagent 分别通过有序 `middleware_refs` 装配多个配置。格式、安全边界和依赖管理见[文件化 Python 扩展](middleware-packages.md)。

Custom Tool 组件同样保存一个配置独占的 Python 扩展，但固定由同步 `create_tool()` 返回一个 LangChain `BaseTool`。Main Agent 和 Subagent 分别通过有序 `tool_refs` 装配多个配置；每个配置对应一个 Tool。完整 contract 见[Custom Tool](../wizard-pages/custom-tool-config.md)。

Agent Additional Prompt（AAP）是推荐的 Agent 初始提示词注入范式，通过普通 Custom Middleware 实现：从 `内置示例-agent-additional-prompt` 创建独立配置，再由需要它的 Main Agent 或 Subagent 通过 `middleware_refs` 选择。完整原理和修改位置见 [Agent Additional Prompt](agent-additional-prompt.md)。

Main Agent是独立Deep Agents root graph，messages和private state由其Thread checkpoint拥有。Workflow通过Command的`runtime.context.agent_runs`创建独立Main Agent Thread/Run并显式读取结果。synchronous Subagent由Deep Agents `SubAgentMiddleware`在current Agent loop内调度；Main Agent的ordered AsyncSubAgent references由官方`AsyncSubAgentMiddleware`启动独立后台Thread/Run。

Workflow Event Output 也是 Workflow-owned 组件。Workflow 通过 UUID 可选绑定一份配置；配置独占扩展中的同步 `output(event, origin)` 读取 LangGraph v3 原始 ProtocolEvent 与 Shell origin，返回类型为字符串。它只控制 Workflow-owned non-Agent 事件的 OpenAI 响应投影，不改变 checkpoint、Debug、最终 State 或 Agent 自己的 Agent Event Output。字段和 Python 对象类型见[Workflow Event Output](../wizard-pages/workflow-event-output-config.md)。

响应流调度是 System Settings 的全局配置。每个新 Lifecycle 冻结当时的静默让位秒数、单批软大小和最小发送间隔；Workflow 与 Main Agent 共享同一套 Run-level 规则，配置不属于 Component 或 Workflow metadata。

Command组件保存一个`workflow-node/command`Python扩展引用和普通config。扩展通过同步`create_command()`工厂物化`async command(state, runtime)`；callable直接返回官方`langgraph.types.Command`。画布outgoing Control Edge声明允许的目标Node ID，脚本以`goto`选择目标并以`update`修改`shared_vars`。需要Agent或另一个Workflow时，脚本调用Runtime Context中的Run facade。
完整 package 和返回契约见[Command Node](../wizard-pages/command-config.md)。

这些自定义 Python 都运行在服务进程的受信任边界内，没有 sandbox。Custom Tool、Custom Middleware、Command Node、Agent Event Output 和 Workflow Event Output 是五类配置独占的 Python 扩展，并在扩展目录可选的 `requirements.txt` 声明外部包；模板和示例本身不运行也不参与依赖。五类目录与通用依赖边界见[文件化 Python 扩展](middleware-packages.md)，各组件的 factory contract 见对应组件页。
启动器收集全部已配置Main Agent assembly，以及enabled Workflow触达扩展的requirements；修改后需重启 Agent Shell 以重建依赖层。文件化扩展源码在下一次请求重新加载。
