# Workflow、Main Agent 与 Subagent

## Workflow

【Workflow】通过【Parent Run Workflow】和【Child Run Workflow】两个子页面管理同一种实体。装配页选择已有 Workflow，或新建并保存名称、角色、说明、
可选 Checkpointer、Workflow Event Output 与 Response Stream Scheduling 组件引用、默认开启的 `cancel_on_upstream_termination`、`recursion_limit`（最大 Super-step 数，默认 `1,000,000`）、`execution_timeout_seconds`（单个 Run 的实际执行超时，不包含把已生成 SSE 文本交给慢速调用方的等待；默认 `1,200` 秒）、`max_concurrency`（并行节点最大并发数，默认 `100`）和一份 current Graph definition/layout。Parent Run Workflow 中该开关显示为【客户端断开时终止运行】；关闭后 OpenAI 流式连接提前断开时 Run 继续执行，只是不再向该连接发送输出。Child Run Workflow 中显示为【父运行取消或失败时终止】；Parent Run 取消或失败时默认一并取消 child，关闭后 child 独立继续。Parent Run 正常到达 End 不触发 child 取消。这些运行值只有正数约束，没有额外的产品上限；实际资源能力取决于 Workflow、Provider、工具、进程和宿主机资源。
`enabled` 是同一 Workflow 的草稿/正式状态，只由 Graph 草稿保存或正式保存切换，metadata 表单不能直接切换。
只有 enabled parent Workflow 出现在 `/v1/models`；child Workflow 不从 OpenAI-compatible 入口直接启动。两个页面复用同一配置表单和画布，
编辑器工具栏显示当前角色并返回对应装配页。新记录保存并获得 UUID 后才能进入【编辑 Flow】；通用列表和 Bundle 操作集中在【配置库】，装配页也提供复制和删除。

Response Stream Scheduling 是【工作流组件】中的可复用配置，进入现有配置库统一管理。组件只包含输出原子、空闲让位时间、批次软大小和最小发送间隔。Parent Run Workflow 通过可空 `response_stream_scheduling_id` 装配一个组件；未装配时使用内置默认调度。每个 Lifecycle 只有一个 Parent Run Workflow，因此引用保存在 Parent Workflow 方便配置管理，策略仍作用于一次公开 response 对应的整个 Lifecycle，并随请求配置快照冻结。Child Run Workflow 不拥有该引用；当前 scheduler 的事件 producer 是 Parent Run，independent child/background Run 是否接入同一 Lifecycle scheduler 保持待定。事件是否公开及其文本修饰由 Agent Event Output 或 Workflow Event Output 唯一决定，调度器不提供第二套可见性、活动文本、首尾修饰或 Node 覆写。字段与 API 示例见[响应流调度](../wizard-pages/response-stream-scheduling-config.md)。

默认输出原子是 `request`：同一 AI model request 的 reasoning、assistant text和已完成 Tool transaction使用同一排队身份。当前原子每收到一个由 Event Output 产生的非空公开文本项都会重新开始空闲让位倒计时；脚本返回空字符串的 reasoning、assistant text或其他普通事件不会取得 writer，也不会延长已有 writer lease。持续产生公开文本时保持 writer，静默超过配置时间后让出，迟到事件从队尾恢复。`message-finish`只关闭模型正文 block，后续 Tool outcome仍可属于同一 request；同一 invocation 的下一次 model request开始或所属 Node terminal时，前一个request已有输出排完后立即让位。慢 Tool不会被timeout取消，Tool call与terminal outcome仍作为不可插队的一个输出项。没有稳定 AI request身份的Command、Workflow或其他非 AI事件各自形成singleton atom。

选择 `node_invocation` 时，同一次 Node实际执行产生的事件使用同一输出原子；相同 Node循环重入或再次启动会得到新的 invocation身份。Node terminal会关闭该invocation尚未结束的公开content segment，并在已有输出排完后立即释放writer；运行中没有新的非空公开文本超过配置时间也会让位。两种策略都不改变LangGraph执行、Provider或Tool timeout。

【批次软大小】按 Event Output 已投影的 UTF-8正文计算。每个排水批次至少发送一个完整输出项，单项自身超过软大小时仍完整发送；其余情况下尽量合并更多已经完成 single-writer排序的输出项。一个传输批次可以跨越相邻输出原子，但只会在调度顺序已经确定后合并，不会造成多来源字符交错；合并结果作为一个 OpenAI `delta.content`发送。首个正文批次立即发送，后续批次遵守【最小发送间隔】。

每个 canvas Agent Node 使用私有 `messages` 运行自己的 Agent graph。Agent 完成后，wrapper 把完整 reduced conversation 作为不可变 artifact 写入 Lifecycle/Run Store；parent State 的 `agent_invocations` 保存 `invocation_id`、Workflow/Node/Agent identity、`invoked_at` 和 `result_ref`。Task Dispatcher worker 的 State reference 携带 task identity。Agent Additional Prompt 可以从 parent State 选择当前因果可见的 reference，再通过 `runtime.store` 读取、校验和转换完整 artifact；Workflow 启用 Checkpointer 时，历史 Checkpoint State 也保留当时可见的 reference。

并行分支读取同一个 LangGraph Super-step snapshot，以不同 invocation ID 返回引用，不按开始时间、结束时间或 mapping 插入顺序解释先后。direct Agent Node invocation 的 State index 按 canvas Node 保留最新逻辑槽，worker invocation 按 Dispatcher Node + task ID 保留最新逻辑槽；旧 artifact 保留到 Lifecycle 清场，因此启用 Checkpointer 时，旧 Checkpoint State 的旧引用仍可读取。

background Run 由应用级 Manager 管理。每个 Run 的官方 Runtime Context 提供 `background_runs` 命令对象，Command Node、Task Dispatcher、
Custom Tool、Middleware 或 executable Node 可以在自己的 invocation 内调用 `start_workflow()`、`check()`、`list()` 和 `cancel()`。启动命令立即返回 handle；查询不需要为了“检查状态”再走一个额外 Node。调用方负责把需要的 handle/snapshot 写入 `background_tasks` 或自己的 State channel，并自行编排循环、延时、retry 和结束条件。只允许启动 enabled child Workflow；需要让一个 Agent 在后台执行时创建 `Start -> Agent -> End` 子图，使该 Run 继续使用标准 Workflow checkpoint、事件和运行配置。

启动参数包含稳定 `operation_id`；去除首尾空白后必须为 1-128 个字符，否则返回 422。相同 caller Run 内因 Node retry 或重新执行而再次调用同一 operation 时返回原 handle，不会重复派遣；同一 operation 绑定不同 target 时返回 409，需要重派到新目标时使用新的 operation ID。
`operation_id` 的幂等范围是 current caller Run；业务重派使用新的 operation ID。Workflow target 只允许 enabled child Workflow，background output 由调用方显式读取和编排。

【系统 / 运行历史】页面按一次 top-level request 列出 Lifecycle，并展示 root/background Run parent/child relationship、结构 Timeline、Checkpoint/Store 摘要、关联诊断以及 single Run/Lifecycle 完整运行详情 ZIP 下载。页面本身不展开运行正文；下载包固定汇总当前已经持久化的 input、Agent invocation artifact、background task、Run/Event、Lifecycle Store 记录和诊断附件，并只为 `checkpoint_thread_id` 非空的 Run 汇总 Checkpoint State。
Lifecycle 的 messages、task records、resolved mapping records，以及已启用 Run 的 checkpoint 默认持续保留，直到用户显式删除；删除时清理全部非空 Checkpoint Thread 和受管的生命周期动态目录。parent Run 尚未终止，或仍有 `pending`、`running`、`cancel_requested` background task 时，删除返回冲突；
parent Run 终止且 background task 经传播、Workflow 代码、Tool/Middleware 或管理操作进入终态后，Lifecycle 可以删除。parent Workflow Graph 正常到达 End 后，background task 与 Lifecycle 按各自 lifecycle 继续保留；parent 取消或失败时，默认取消仍启用【父运行取消或失败时终止】的直接 child。
删除开始后 Lifecycle 进入 `deleting` 并冻结 background Run 创建；清理失败时保留该状态，可由用户再次执行删除继续清场。

【编辑 Flow】进入独立全屏 Vue Flow 页面。左右各有一条始终保留的工具图标轨；点击 active 图标只收起功能 panel，图标轨不会消失。左侧提供组件库、元素追踪和问题：组件库提供当前角色允许的 Agent、Command 和 Task Dispatcher，可以点击或拖到画布；元素追踪列出当前全部 Node，
点击条目会保持当前缩放、把 Node 平滑移到视口中心并打开右侧属性；存在问题时问题图标显示红色数量角标，点击后在左侧列出当前问题。右侧属性使用紧凑的 `key : value/control` 行，编辑所选 Node 或 Edge；空白点击会清除选择并收起属性，平移、缩放和拖动不会触发收起，重新打开空选择属性时显示 Workflow 名称和 State contract。

选中连线后，可以选择两端共同支持的 Edge 类型、具体 source/target endpoint，也可以删除连线。Normal、Branch 与 Dispatch Edge 都使用 Bezier 曲线；Branch/Dispatch key 在 Edge 属性中填写并保存，不显示在线段上，两种dynamic Edge 仍以不同虚线、动画、箭头和端点名称区别。
问题列表显示 current candidate Graph 的全部正式问题；点击问题可以选中对应 Node、Edge 或 Workflow，画布底部不承载问题 UI。Graph 不设置 Node、Edge 数量或 document 字节数的领域配额；实际可用规模取决于浏览器、请求、存储、LangGraph 和本机资源。同一个 Main Agent 可以被多个 Agent Node 重复引用；normal 端点可以连接 `Start -> Agent`、
`Agent -> Agent` 和 `Agent -> End`，并允许一个 endpoint 连接多个 activation direction。保存直接覆盖 current Graph，重新打开时恢复 Node、Edge、position 和 viewport。草稿保存执行 wire validation 并原子设置 `enabled=false`；正式保存执行完整静态校验，通过后原子写入 Graph 并设置 `enabled=true`。current canvas revision 的预校验请求失败时，正式保存保持禁用并显示重新校验操作；正式失败不落盘。

保存入口允许不完整 draft。publishable Graph 恰有一个 system Start 和一个 system End，且 Start 至少有一条合法 outgoing Edge；`Start -> End` 可以 publish，End 可以没有 incoming Edge。LangGraph runtime 允许 reachable leaf Node 在没有 successor message 时自然结束。每个 executable Node 都从 Start 可达；不满足 topology fact、Edge paradigm 或 LangGraph compile requirement 时，在 Agent assembly 和 Graph compile 前返回 422。

普通可达叶子可以自然结束。多条路径集中结束时，路径显式汇聚到实际执行的 Node（例如 Command Node），再由该 Node 连接 End。End 表示逻辑终点；all-of fan-in 在全部声明的 source Node 完成后激活 target。互斥分支适合作为独立叶子或分别连接 End。

canvas Start/End 分别映射 LangGraph 官方虚拟 `START/END`，不编译成 Shell 函数节点；Start 的初始激活不参与普通 all-of fan-in，
所以 `Start -> A` 与后续 `B -> A` 可以直接表达循环入口。End 是系统提供的固定逻辑终点。
Agent Node 引用的 `main_agent_id` 保存在 Graph definition 中。`normal` 是 Node endpoint type；从 normal output endpoint 画到 normal input endpoint 的线表达 successor Node 的 activation direction。Node endpoint 来自后端 Catalog 的 input/output arrays，保存时记录 `source_handle`/`target_handle`。多条 Normal Edge 按 LangGraph 官方 Graph API 激活多个 successor Node；parent Workflow State 由后端 contract 管理。

Task Dispatcher Node 引用一份 `workflow-node` family / `task-dispatcher` adapter 的配置独占 Python 包。它从 current Workflow State/Runtime Context 生成运行时数量的任务，并由 compiler 转成 LangGraph `Send`；画布只保存一个 Dispatcher Node 和具名 Dispatch Edge，
画布始终保存一个 Dispatcher Node 和具名 Dispatch Edge。同一个 Agent Node 可被不同 payload 多次调用，或由不同 `dispatch_key` 路由到不同 Agent Node。每次 worker 调用都在 private Agent State 的 `workflow_task` 中得到任务，完成记录也保存该 task identity。完整配置与城市/乡镇示例见[Task Dispatcher](../wizard-pages/task-dispatcher-config.md)。

## Main Agent 与 Subagent

在【代理 / Main Agent】选择模型要求和 Agent Event Output 等 capability。Main Agent 是完整 Agent 装配，由 Workflow 的 Agent Node 引用。需要同步委派时，先创建 Subagent 实体，再由 Main Agent 按顺序保存 `subagent_id` 引用并选择委派 capability。

Main Agent 必须分别选择 Filesystem Backend 与 Filesystem Tools。Backend 在 CompositeBackend 和 LocalShellBackend 中二选一；Tools 独立控制文件 Tool visibility、description 与参数。Subagent 对两者分别继承或替换，required capability 不能关闭；Workflow metadata 不保存 Filesystem。

CompositeBackend 的每条映射或虚拟来源直接保存 `read-write|read-only|no-access` 权限，并可通过 `skill_package_id` 引用 Skill 独立包。Skill 引用、路径与权限随 Backend 一起被 Subagent 继承。LocalShellBackend 只使用固定真实工作区，不接受 Skill 包或 Composite 来源；`execute` 只有在 Tools 开启且 Backend 为 LocalShellBackend 时可见。

Subagent settings 定义身份、说明、capability 覆写和自己的 ordered Middleware 引用。当前委派结构为一层同步 `Main -> Subagent`，运行时使用 Deep Agents 官方 dictionary-based CompiledSubAgent。Agent 内部通过 `SubAgentMiddleware`/`task` 委派；外层 Workflow 的节点和边负责多阶段、并行、条件和 join。

## Custom Middleware

Summarization 与 Prompt Caching 是两个独立组件。Main Agent 可以分别选择或不选择，Subagent 按 capability 的继承/替换/关闭规则得到自己的最终配置；后端为每个身份显式物化官方 middleware，不依赖声明式 Subagent 自动继承 Main Agent 的 middleware 实例。

每个 Custom Middleware 组件定义一个 Middleware。Main Agent 和 Subagent 各自保存有序 `middleware_refs`，列表顺序就是多个用户 Middleware 的装配顺序。Shell 加载扩展包并把官方 `AgentMiddleware` 实例交给 `create_deep_agent()`；运行行为由 LangChain Middleware hook 提供。

客户端 `messages[]` 是外围不可变请求事实，不会自动成为 Main Agent 活动消息。需要消息策略时，由 Middleware 在 `before_agent`/`abefore_agent` 中读取官方 state/context，按 Agent 身份整理后返回官方 state update。Main Agent 可用 `runtime.context.lifecycle_id` 从 `runtime.store` 读取冻结的 Lifecycle 输入；Subagent 默认保留 Deep Agents delegated messages，不自动附加根请求。格式见[Custom Middleware 包](middleware-packages.md)。

### Agent Additional Prompt Middleware

Agent Additional Prompt（AAP）通过 Custom Middleware 的 `abefore_agent` 构造 current Agent 私有初始提示词。从 `内置示例-agent-additional-prompt` 创建配置后，由需要它的 Main Agent 或 Subagent 通过有序 `middleware_refs` 选择并排序。
Main Agent 可以从 Lifecycle Store 读取不可变请求快照，Subagent template 默认使用 delegated messages；upstream Agent 输出和 Workflow 文件由当前 AAP 代码选择。完整约定见 [Agent Additional Prompt](agent-additional-prompt.md)。

AAP 可以读取 `state["workflow_task"]`，把当前任务材料编排进 worker 的私有 `messages`。动态任务集合由 Task Dispatcher 在一个确定的 LangGraph Node invocation 中生成。

### 事件输出

Workflow 可绑定零或一个事件输出组件。它处理 `custom`、`lifecycle`、`values`、`updates`、`tasks` 等 Workflow-owned non-Agent v3 事件；
每类事件由配置独占 Python package 中的同步 `output(event)` 处理，直接读取稳定 dict 和其中的原始 Python `data` 对象并返回字符串。不绑定时这些事件不进入 OpenAI 响应。Agent Node 事件仍使用对应 Main Agent 的 Agent Event Output。完整字段见[事件输出](../wizard-pages/workflow-event-output-config.md)。

Agent Event Output 与 Workflow Event Output 是公开响应的唯一输出模式。每个规范化事件先执行所属 `output(event)`；空字符串不进入公开输出队列，也不刷新输出原子的空闲倒计时，非空字符串携带原有request/invocation身份进入响应流调度。运行时仍可消费无正文的request、content和Node terminal控制边界来关闭segment或释放atom，但不会把它们变成公开文本。调度器只能排序、保持Tool transaction原子和按批次排水。`assistant_text`与`reasoning`使用additive `start / delta / end`：首文本写在`start`，每个`delta`只返回新增文本，尾文本写在`end`。非流式完整正文由投影层机械展开为`start -> delta(完整正文) -> end`，同一脚本无需判断Provider是否流式，也不会在每个delta重复首尾修饰。已收到delta时相信delta拼接；finish snapshot不一致只用于诊断，不能重复公开正文或终止Run。

## 校验与生效

Main Agent 与 Subagent 编辑页继续提交完整草稿给后端预校验，保存时再次校验。`PUT /api/workflows/{id}/draft` 只做 wire 解析并停用；
`POST /api/workflows/{id}/validate` 返回正式静态问题；`PUT /api/workflows/{id}/graph` 重复完整校验并正式启用，metadata PUT 保留既有 enabled。真实 Chat 请求从一次文件配置快照读取 Workflow current Graph、
Main Agent、Subagent、各自 Filesystem Backend、Filesystem Tools、组件和 Provider secret view，完成 Agent 构造后关闭配置快照。
