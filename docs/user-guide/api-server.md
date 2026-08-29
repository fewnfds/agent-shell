# API Server

首页显示接入地址和配置告警。API Server 运行状态与启动、停止按钮位于管理台 navbar，在所有页面可见；
API Key 位于【系统 / 系统配置】的网络卡片，单次请求初始消息条数上限 `max_initial_messages` 位于请求与限制策略卡片；两者由 `PUT /api/api-server` 一起保存。

## 接口

```http
GET /v1/models
Authorization: Bearer <API Key>
```

返回 OpenAI-compatible list；`data[].id` 使用当前启用的 parent Workflow name。

```http
POST /v1/chat/completions
Authorization: Bearer <API Key>
Content-Type: application/json

{
  "model": "writing-workflow",
  "messages": [{"role": "user", "content": "Write a summary."}],
  "stream": false
}
```

请求只按 parent Workflow name 捕获一次配置快照，从同一快照读取 current Graph 和 canvas Agent Node reference，再递归构造 Main Agent、Subagent、各自 Filesystem、权限、Middleware、组件和 Provider secret view。构造完成后关闭请求配置快照，
运行阶段使用该请求开始时捕获的配置快照。

Chat 请求体、content block、输入媒体单项/合计和输出媒体边界由【系统 / 系统配置】的限制策略决定；
`GET /api/system/runtime-policy` 返回后端当前值、默认值、最小值和可配置字段，前端不复制隐藏上限。策略只有后端返回的正数最小值约束，没有额外产品最大值，实际仍受 Provider、
内存、磁盘和网络能力影响。

当前可执行 Node class 为 Start、Agent、Command 和 End，Edge class 为 normal、branch 与 dispatch；一张图可以包含多个 Agent Node，并可串联、
fan-out、fan-in 或形成 LangGraph 支持的循环。canvas Start/End 直接映射 LangGraph 官方 `START/END`，Normal Edge 映射 `StateGraph.add_edge()`；Command 脚本读取完整 Workflow State 和 Runtime Context，可同时返回 State partial update、Branch key 与具名 JSON dispatch task。runtime 把 Branch target 与每个 LangGraph `Send` 放入同一个 `Command.goto`，并把 `workflow_task` 放入 target Agent 的私有 State。Start 不注入客户端消息。规范化后的 `messages[]` 保存在 Lifecycle Store；Runtime Context 只携带定位输入所需的 lifecycle/run/invocation 身份。只有已装配的 `before_agent`/`abefore_agent` Middleware 决定如何读取、切割并写入 Agent state。

每个 Workflow 显式配置 `cancel_on_upstream_termination`、`recursion_limit`、`execution_timeout_seconds` 和 `max_concurrency`。终止传播开关默认开启：parent 的 OpenAI 流连接提前断开时取消 Run；background child 的 parent Run 取消或失败时取消 child。关闭后对应 Run 独立继续；正常 End 不触发 child 取消。三个运行值默认分别是 `1,000,000`、`1,200` 秒和 `100`，只有正数约束，没有额外的产品上限。`recursion_limit` 与 `max_concurrency` 传给 LangGraph Runnable config；`execution_timeout_seconds` 限制单个 parent 或 child Run 的实际执行时间，不包含生成器停在 `yield` 等待慢速调用方消费已生成 SSE 文本的时间。

Workflow 通过可空 `checkpointer_id` 选择一个【检查点保存器】（Checkpointer）组件，默认选择【无】。未选择时 Graph 使用 `checkpointer=None` 编译，不生成 `checkpoint_thread_id`、不传 durability，也不会因本次 Run 建立或访问 checkpoint SQLite；最终 State、Lifecycle、Run/Event/Model Request History、Store、Agent invocation artifact、background Run、Tracing、Diagnostics 和 usage 仍按各自 owner 工作。选择后，每个 Workflow Run 生成独立的检查点线程，并把组件的 `durability=exit|async|sync` 传给 LangGraph；Canvas Agent/Deep Agent subgraph 使用官方默认继承该 saver。parent Workflow 与 background child Workflow 分别读取自己的 `checkpointer_id`。

Checkpointer 当前只为运行历史提供 Debug 检查点，不提供 Resume 或灾难恢复入口。`exit` 在 Graph 正常结束、报错或触发 interrupt 时写入，运行期开销最低但进程崩溃会丢失中间状态；`async` 在下一步执行时异步写入，默认用于平衡延迟与持久性；`sync` 在下一步开始前完成写入，持久性最强且写入延迟最高。

Parent Run Workflow 通过可空 `response_stream_scheduling_id` 引用【工作流组件】中的 Response Stream Scheduling 配置。未装配时使用内置默认；装配后从当前请求冻结的 Configuration Repository 快照读取 request/node invocation 输出原子、闲置让位秒数、批次软大小和最小发送间隔。Child Run Workflow 不接受该引用。组件只调度 Agent/Workflow Event Output 已批准的文本，不拥有事件可见性或修饰规则。

`stream=false` 返回标准 `chat.completion` JSON。`stream=true` 返回 `chat.completion.chunk` SSE，并以 `data: [DONE]` 结束。一次 OpenAI response 创建一个 Lifecycle Response Scheduler，当前 Parent Run 的规范化 LangGraph v3 事件通过 typed input 进入它；任一时刻只有一个 lane 可以向 append-only assistant 字符串写入。两种模式消费同一 frame sequence，因此流式 content chunk 拼接结果与非流式 message content 一致。

响应流策略作用于整个 Lifecycle。每个 Lifecycle 只有一个 Parent Run Workflow，因此 Parent Workflow只保存组件引用并随启动快照冻结，这只是配置管理归属。策略只配置 request/node invocation 输出原子、空闲让位时间、批次软大小和最小发送间隔。所有规范化事件先经过所属 Agent Event Output 或 Workflow Event Output；脚本返回空字符串时不进入响应且不刷新writer lease，返回非空字符串时才作为公开文本交给scheduler排队。无正文的content/request/Node terminal控制边界仍可关闭segment或释放atom。reasoning与assistant text使用统一的additive `start / delta / end`投影：流式delta实时进入脚本，非流式完整正文机械展开为单个delta，已有真实delta时finish snapshot不重复正文。Tool call与terminal outcome分别投影，再作为不可插队的原子项输出；`message-finish`不代表关联Tool已经完成，慢Tool等待超过空闲时间后只释放当前位置。同一invocation的下一次model request开始或Node terminal是前一个request的确定结束边界，不等待idle timeout才让位。

## 拦截消息

【系统 / 拦截消息】提供一个独立于 Workflow 的 Shell 入站开关。开启后，合法 Chat Completions 请求完成鉴权、
请求体大小限制和基础 OpenAI 字段检查（含 `max_initial_messages` 数量上限）后立即短路，不捕获 Workflow 配置快照，不装配 Agent，也不创建 checkpoint。
调用方按原 `stream` 模式收到 OpenAI-compatible 的“消息已拦截”回复，token usage 为零。

页面通过 management-only API 显示进程内最新一条请求原文。开关持久化，正文仅保存在当前进程；开关从关闭变为开启或服务重启时清空原文。

## 运行边界

- Workflow 保存一份 current Graph；草稿保存设置 `enabled=false`，正式保存通过完整校验后设置 `enabled=true`；
- parent/child 是同一 Workflow 实体的使用角色，`/v1` 入口启动 parent Workflow；
- 每次请求执行一次完整运行；`run_id` 是所有 Run 的执行身份，只有引用 Checkpointer 的 Workflow Run 额外建立独立 `checkpoint_thread_id` 并使用官方持久 saver；
- background Workflow Run 通过 Runtime Context 的 `background_runs` 命令启动和查询；需要单 Agent 后台任务时使用 `Start -> Agent -> End` child Workflow。Command Dispatch 在请求内生成动态 Agent invocation，多个 normal 出边、一次激活的多个 Branch target 和多个 Send task 按 LangGraph Super-step 语义执行；
- independent child/background Run 使用自己的 `RunExecution` 并保持 `public_output=false`；其事件接入 Parent Run response scheduler 的来源层级和 Event Output owner 尚未定义；
- 图不完整、引用失效、Agent 装配失败或 Provider 失败时，本次请求返回对应错误；
- 日志中心展示系统事件和结构化运行失败诊断，运行异常自动尝试保存 traceback 附件；
- management-only `/api/workflow-lifecycles` 提供运行历史列表、Lifecycle/Run 详情、结构事件分页、完整运行详情 ZIP 下载和显式删除。列表使用 `page/page_size/query` 后端分页；`POST /api/workflow-lifecycles/delete` 使用相同 `query` 一次清理完整匹配集中的已终止 Lifecycle，并返回删除数和保留的 active 记录数。详情页面提供结构记录、Checkpoint/Store 摘要与关联诊断。Lifecycle/Run ZIP 固定导出当前持久化的运行输入、Agent invocation artifact、按 Main Agent/Subagent profile 分文件的 LangChain `on_chat_model_start` 消息、Tool schema 与调用参数、background task、Run/Event、Lifecycle Store 记录和诊断附件；只为 `checkpoint_thread_id` 非空的 Run 导出 complete Checkpoint State。删除在 parent 和 background task 进入终态后执行，并可清理受管动态目录。

## API Key 与状态

API Key 是 write-only 设置，用于 `/v1/*`；管理密码用于管理台和 `/api/*`。清除 API Key 后推理 API 不可用。
API Server 启停不扫描未被 Workflow 引用的 Main Agent；完整 repository validation 只用于管理诊断，单次 Chat 请求只解析所选 Workflow 的 current Graph 和可达装配。

普通 API response、DOM 和 log summary 仅提供脱敏后的公开字段；management-only 的 local exception-detail attachment 保留完整排错信息。
