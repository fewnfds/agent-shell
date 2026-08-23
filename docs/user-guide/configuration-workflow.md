# Workflow、Main Agent 与 Subagent

## Workflow

【Workflow】按父图和子图两个子页面管理同一种实体。装配页选择已有 Workflow，或新建并保存名称、角色、说明、
可选事件输出组件引用、`recursion_limit`（最大 super-step 数，默认 `1,000,000`）、`execution_timeout_seconds`（单个 Run 的实际执行超时，不包含把已生成 SSE 文本交给慢速调用方的等待；默认 `1,200` 秒）、`max_concurrency`（并行节点最大并发数，默认 `100`）和一份当前 Graph definition/layout。这些运行值只有正数约束，没有额外的产品上限；实际资源能力取决于 Workflow、Provider、工具、进程和宿主机资源。
`enabled` 是同一 Workflow 的草稿/正式状态，只由 Graph 草稿保存或正式保存切换，metadata 表单不能直接切换。
只有启用的父图出现在 `/v1/models`；子图不从 OpenAI-compatible 入口直接启动。两个页面复用同一配置表单和画布，
编辑器工具栏显示当前角色并返回对应装配页。新记录保存并获得 UUID 后才能进入【编辑 Flow】；通用列表和 Bundle 操作集中在【配置库】，装配页也提供复制和删除。

每个画布 Agent 节点使用私有 `messages` 运行自己的 Agent graph。Agent 完成后，wrapper 把完整 reduced conversation 作为不可变 artifact 写入 Lifecycle/Run Store；父 State 的 `agent_invocations` 保存 `invocation_id`、Workflow/Node/Agent 身份、`invoked_at` 和 `result_ref`。Task Dispatcher worker 的 State 引用携带 task identity。Workflow Input Context 从父 State 选择当前 checkpoint 可见的引用，再通过 `runtime.store` 读取、校验和转换完整 artifact。

并行分支读取同一个 LangGraph super-step snapshot，以不同 invocation ID 返回引用，不按开始时间、结束时间或 mapping 插入顺序解释先后。普通 Agent 的 State 索引按画布 Node、worker 按 Dispatcher Node + task ID 保留最新逻辑槽；旧 artifact 保留到 Lifecycle 清场，因此旧 checkpoint 的旧引用仍可读取。

后台 Run 由应用级 Manager 管理。每个 Run 的官方 Runtime Context 提供 `background_runs` 命令对象，Command Node、Task Dispatcher、
Custom Tool、Middleware 或普通 Node 可以在自己的 invocation 内调用 `start_agent()`、`start_workflow()`、`check()`、`list()` 和 `cancel()`。启动命令立即返回 handle；查询不需要为了“检查状态”再走一个额外 Node。调用方负责把需要的 handle/snapshot 写入 `background_tasks` 或自己的 State channel，并自行编排循环、延时、retry 和结束条件。

启动参数包含稳定 `operation_id`；去除首尾空白后必须为 1-128 个字符，否则返回 422。相同 caller Run 内因 Node retry 或重新执行而再次调用同一 operation 时返回原 handle，不会重复派遣；同一 operation 绑定不同 target 时返回 409，需要重派到新目标时使用新的 operation ID。
`operation_id` 的幂等范围是当前 caller Run；业务重派使用新的 operation ID。Workflow target 只允许已启用子图，后台 Agent 使用自身有效 Filesystem，后台输出由调用方显式读取和编排。

【系统 / 运行历史】页面按一次顶层请求列出 Lifecycle，并展示 root/background Run 父子关系、结构 Timeline、Checkpoint/Store 摘要、关联诊断以及单 Run/Lifecycle 诊断包下载。Event Journal 只保存结构身份、状态、时间和 usage，不复制运行正文。
Lifecycle 的 messages、task records、resolved mapping records 和 parent/child checkpoint 默认持续保留，直到用户显式删除；删除时同时清理受管的生命周期动态目录。父 Run 尚未终止，或仍有 `pending`、`running`、`cancel_requested` 后台任务时，删除返回冲突；
父 Run 终止且后台任务经 Workflow 代码、Tool/Middleware 或管理操作进入终态后，Lifecycle 可以删除。父图到达 End 后，后台任务与 Lifecycle 按各自生命周期继续保留。
删除开始后 Lifecycle 进入 `deleting` 并冻结后台 Run 创建；清理失败时保留该状态，可由用户再次执行删除继续清场。

【编辑 Flow】进入独立全屏 Vue Flow 页面。左右各有一条始终保留的工具图标轨；点击 active 图标只收起功能 panel，图标轨不会消失。左侧提供组件库、元素追踪和问题：组件库提供当前角色允许的 Agent、Command 和任务分发，可以点击或拖到画布；元素追踪列出当前全部 Node，
点击条目会保持当前缩放、把 Node 平滑移到视口中心并打开右侧属性；存在问题时问题图标显示红色数量角标，点击后在左侧列出当前问题。右侧属性使用紧凑的 `key : value/control` 行，编辑所选 Node 或 Edge；空白点击会清除选择并收起属性，平移、缩放和拖动不会触发收起，重新打开空选择属性时显示 Workflow 名称和 State contract。

选中连线后，可以选择两端共同支持的 Edge 类型、具体 source/target endpoint，也可以删除连线。Normal、Branch 与 Dispatch Edge 都使用 Bezier 曲线；Branch/Dispatch key 在 Edge 属性中填写并保存，不显示在线段上，两种动态 Edge 仍以不同虚线、动画、箭头和端点名称区别。
问题列表显示当前候选 Graph 的全部正式问题；点击问题可以选中对应 Node、Edge 或 Workflow，画布底部不承载问题 UI。Graph 不设置 Node、Edge 数量或 document 字节数的领域配额；实际可用规模取决于浏览器、请求、存储、LangGraph 和本机资源。同一个 Main Agent 可以被多个 Agent node 重复引用；normal 端点可以连接 `Start -> Agent`、
`Agent -> Agent` 和 `Agent -> End`，并允许一个端点连接多个激活方向。保存直接覆盖当前图，重新打开时恢复节点、边、位置和 viewport。草稿保存执行 wire validation 并原子设置 `enabled=false`；正式保存执行完整静态校验，通过后原子写图并设置 `enabled=true`。当前画布 revision 的预校验请求失败时，正式保存保持禁用并显示重新校验操作；正式失败不落盘。

保存入口允许不完整 draft。正式 Graph 恰有一个系统 Start 和一个系统 End，且 Start 至少有一条合法出边；`Start -> End` 可以正式保存，End 可以没有入边。LangGraph runtime 允许可达普通叶子在没有后继消息时自然结束。每个参与运行的节点都从 Start 可达；不满足结构事实、边范式或 LangGraph 编译要求时，在 Agent 装配和 Graph compile 前返回 422。

普通可达叶子可以自然结束。多条路径集中结束时，路径显式汇聚到实际执行的 Node（例如 Command Node），再由该 Node 连接 End。End 表示逻辑终点；all-of fan-in 在全部声明的 source Node 完成后激活 target。互斥分支适合作为独立叶子或分别连接 End。

画布 Start/End 分别映射 LangGraph 官方虚拟 `START/END`，不编译成 Shell 函数节点；Start 的初始激活不参与普通 all-of fan-in，
所以 `Start -> A` 与后续 `B -> A` 可以直接表达循环入口。End 是系统提供的固定逻辑终点。
Agent 节点引用的 `main_agent_id` 保存在 Graph definition 中。`normal` 是节点端点类型；从 normal 输出端点画到 normal 输入端点的线表达后继节点的激活方向。Node 端点来自后端 Catalog 的 input/output arrays，保存时记录 `source_handle`/`target_handle`。多条 normal 出边按 LangGraph 官方 Graph API 激活多个后继节点；父 Workflow State 由后端 contract 管理。

任务分发节点引用一份 `workflow-node` family / `task-dispatcher` adapter 的配置独占 Python 包。它从当前 Workflow State/Runtime Context 生成运行时数量的任务，并由 compiler 转成 LangGraph `Send`；画布只保存一个 Dispatcher Node 和具名 Dispatch Edge，
画布始终保存一个 Dispatcher Node 和具名 Dispatch Edge。同一个 Agent Node 可被不同 payload 多次调用，或由不同 `dispatch_key` 路由到不同 Agent Node。每次 worker 调用都在私有 Agent State 的 `workflow_task` 中得到任务，完成记录也保存该 task identity。完整配置与城市/乡镇示例见[任务分发](../wizard-pages/task-dispatcher-config.md)。

## Main Agent 与 Subagent

在【代理 / Main Agent】选择模型要求和 Agent 事件输出等 capability。Main Agent 是完整 Agent 装配，由 Workflow 的 Agent node 引用。需要同步委派时，先创建 Subagent 实体，再由 Main Agent 按顺序保存 `subagent_id` 引用并选择委派 capability。

Main Agent 可选择项目 Filesystem 或最小 Filesystem，Subagent 可继承、选择自己的项目 Filesystem 或回到最小 Filesystem；Workflow metadata 不保存 Filesystem。
每个身份也可以选择自己的 `filesystem-permissions`。权限配置同时控制路径权限和该身份可见的文件工具；运行时按 Agent 的有效 Filesystem 与权限组合并冻结 backend 路由视图。

Subagent settings 定义身份、说明、capability 覆写和自己的有序 Middleware 引用。当前委派结构为一层同步 `Main -> Subagent`，运行时使用 Deep Agents 官方 dictionary-based CompiledSubAgent。Agent 内部通过 `SubAgentMiddleware`/`task` 委派；外层 Workflow 的节点和边负责多阶段、并行、条件和 join。

## 自定义 Middleware

Summarization 与 Prompt Caching 是两个独立组件。Main Agent 可以分别选择或不选择，Subagent 按 capability 的继承/替换/关闭规则得到自己的最终配置；后端为每个身份显式物化官方 middleware，不依赖声明式 Subagent 自动继承 Main Agent 的 middleware 实例。

每个 Custom Middleware 组件定义一个 Middleware。Main Agent 和 Subagent 各自保存有序 `middleware_refs`，列表顺序就是多个用户 Middleware 的装配顺序。Shell 加载扩展包并把官方 `AgentMiddleware` 实例交给 `create_deep_agent()`；运行行为由 LangChain Middleware hook 提供。

客户端 `messages[]` 是外围不可变请求事实，不会自动成为 Main Agent 活动消息。需要消息策略时，由 Middleware 在 `before_agent`/`abefore_agent` 中读取官方 state/context，按 Agent 身份整理后返回官方 state update。Main Agent 可用 `runtime.context.lifecycle_id` 从 `runtime.store` 读取冻结的 Lifecycle 输入；Subagent 默认保留 Deep Agents delegated messages，不自动附加根请求。格式见[自定义 Middleware 包](middleware-packages.md)。

### Workflow 输入上下文 Middleware

Workflow Input Context 通过 Custom Middleware 的 `abefore_agent` 构造当前 Agent 私有消息。从 `内置示例-workflow-input-context` 创建配置后，由 Main Agent 或 Subagent 的有序 `middleware_refs` 选择并排序。
Main Agent 可以从 Lifecycle Store 读取不可变请求快照，Subagent 默认使用 delegated messages；前序 Agent 输出和 Workflow 文件由当前 WIC 代码选择。完整约定见[Workflow Input Context](workflow-input-context.md)。

WIC 可以读取 `state["workflow_task"]`，把当前任务材料编排进 worker 的私有 `messages`。动态任务集合由 Task Dispatcher 在一个确定的 LangGraph Node invocation 中生成。

### 事件输出

Workflow 可绑定零或一个事件输出组件。它处理 `custom`、`lifecycle`、`values`、`updates`、`tasks` 等 Workflow-owned 非 Agent v3 事件；
每类事件由配置独占 Python package 中的同步 `output(event)` 处理，直接读取稳定 dict 和其中的原始 Python `data` 对象并返回字符串。不绑定时这些事件不进入 OpenAI 响应。Agent Node 事件仍使用对应 Main Agent 的 Agent 事件输出。完整字段见[事件输出](../wizard-pages/workflow-event-output-config.md)。

## 校验与生效

Main Agent 与 Subagent 编辑页继续提交完整草稿给后端预校验，保存时再次校验。`PUT /api/workflows/{id}/draft` 只做 wire 解析并停用；
`POST /api/workflows/{id}/validate` 返回正式静态问题；`PUT /api/workflows/{id}/graph` 重复完整校验并正式启用，metadata PUT 保留既有 enabled。真实 Chat 请求从一次文件配置快照读取 Workflow 当前图、
Main Agent、Subagent、各自 Filesystem、组件和 Provider secret view，完成 Agent 构造后关闭配置快照。
