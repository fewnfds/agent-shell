# API Server

首页使用【服务入口】和【API 端点】两张 Card 展示当前实例地址、LangGraph 官方路径族、诊断端点与认证边界。OpenAI-compatible Base URL 是 `<origin>/compat/openai/v1`；Agent Shell API Base URL 是 `<origin>/agent-shell/api`。API Server 运行状态与启动、停止按钮位于管理台 navbar，在所有页面可见；
API Key 位于【系统 / 系统配置】的 API Server Card，由 `PUT /agent-shell/api/api-server` 保存。

## 接口

```http
GET /compat/openai/v1/models
Authorization: Bearer <API Key>
```

返回OpenAI-compatible list；`data[].id`来自`enabled=true`且`is_model_entry=true`的Main Agent/Workflow name。

```http
POST /compat/openai/v1/chat/completions
Authorization: Bearer <API Key>
Content-Type: application/json

{
  "model": "writing-workflow",
  "messages": [{"role": "user", "content": "Write a summary."}],
  "stream": false
}
```

请求按model name捕获一次配置记录和值视图。Repository YAML、Model/MCP Connection、binding与response policy对该请求保持只读；private Python/Skill package只捕获所在路径，实际源码由Graph factory装配时从磁盘读取，因此运行期间编辑package可能影响尚未装配的Graph。Agent入口通过 LangChain `create_agent()` 和显式 middleware stack 物化所选Main Agent Graph；Workflow入口物化current Start/Command/End control Graph。两者都由稳定Assistant启动官方Thread/Run并由LangGraph Dev Worker执行。Command需要AI时通过`runtime.context.agent_runs`启动独立Main Agent Thread/Run。官方ProtocolEvent由对应Graph的Agent或Workflow Event Output、Lifecycle Response Scheduler和OpenAI response writer消费。

Agent Shell 校验 OpenAI-compatible 消息结构、内容来源、MIME 与 Base64 格式，不设置项目级请求体、消息条数、content block 数量或解码媒体字节上限。实际能力仍受 Provider、内存、磁盘和网络影响。

Workflow可执行Node class为Start、Command和End，只有一种Control Edge。canvas Start/End直接映射LangGraph官方`START/END`；Start Edge映射`StateGraph.add_edge()`，Command outgoing Edge只声明允许的dynamic destination。Command脚本读取只含`shared_vars`的Workflow State和Runtime Context，直接返回官方`Command(update, goto)`。Workflow入口的规范化`messages[]`保存在本次Lifecycle的Server Store namespace而不进入Workflow State。Agent入口把`messages[]`作为所选Main Agent的官方Run input写入AgentState，装配的`before_agent`/`abefore_agent`Middleware可在自己的State边界内整理它。

Main Agent 与 Workflow 显式配置`on_disconnect`。实例级`recursion_limit`、可选`max_concurrency`和`n_jobs_per_worker`位于【系统 / 系统配置 / 限制策略】，使用LangGraph/LangChain官方字段；`max_concurrency`留空时不向运行配置传值。全部Main Agent/Workflow Run都使用持久Thread，checkpoint、State与history由LangGraph Dev官方运行时拥有，durability 使用服务端默认`async`。

每个 Main Agent 与 Workflow 独立保存`on_disconnect=cancel|continue`，界面名称为【用户断开】，默认`cancel`。创建每个 Run 时会把目标资源的值冻结进 Lifecycle relation；用户在 Run 完成前断开时，只取消选择`cancel`的 active Run，选择`continue`的 Run 继续执行。断开之后才登记的 Run 也立即执行自己的冻结策略。其他 Run 的成功、失败或主动取消不会触发隐式连锁取消，调用关系不传播策略。

【系统 / 系统配置 / 响应流调度】保存全局 `idle_timeout_seconds`、`max_batch_kb` 和 `send_interval_seconds`。每个新请求冻结当时的设置并为 Lifecycle 创建一个 scheduler；保存新值不要求重启，也不改变已运行的 Lifecycle。该设置只调度 Agent/Workflow Event Output 已批准的 presentation frame，不拥有事件可见性或修饰规则。

`stream=false` 返回标准 `chat.completion` JSON。`stream=true` 返回 `chat.completion.chunk` SSE，并以 `data: [DONE]` 结束。一次 OpenAI response 创建一个 Lifecycle Response Scheduler，各 participating Run 的 Event Output producer 将已投影 frame 提交给它；任一时刻只有一个 `(thread_id, run_id)` 可以向 append-only assistant 字符串写入。两种模式消费同一 frame sequence，因此流式 content chunk 拼接结果与非流式 message content 一致。

失败响应保留稳定 `error.code` 和 `request_id`，Lifecycle 已建立时还返回 `lifecycle_id`。请求入参校验失败保留其固定文案；异常派生的失败只返回固定英文分类消息，不返回异常类型或异常链。完整原因、源异常类型、具体异常链与 traceback 附件保存在日志中心，凭 `request_id` / `lifecycle_id` 定位；跨 Agent Server 时附件同时包含 Server source traceback。Provider、Tool 和 Graph 分类只增加 code/status，不会把原因改写为固定文案。入口 Run 创建前失败的 Lifecycle 状态为 `error`，其 `run_count` 可以为零。

Lifecycle snapshot只选择正式 Main Agent/Workflow并冻结配置记录、package folder和Filesystem path等引用，不在每次请求前读取、hash、AST parse或导入private Python package。package缺失、语法、import、factory或执行错误在真实Graph装配/执行边界自然失败：响应流尚未建立时返回JSON error，已经建立时发送`finish_reason=error`的SSE chunk；两种时序都会把具体异常链写入运行诊断，响应只给分类消息。

路由没有分类处理的意外异常使用 `internal_error` code 并写入运行诊断。`/agent-shell/api/*` 出口直接返回异常类型与具体异常链；`/compat/openai/v1/*` 出口只返回固定英文分类消息。该 catch-all 不把原因替换为固定的 internal operation 文案。

响应流策略作用于整个 Lifecycle。入口 Run 与其直接或间接启动并登记的普通 Run 共用 scheduler。Run 注册只登记 producer；首个含公开文本或可公开 segment end 的 frame 使该 Run 进入 FIFO ready queue，持续返回空字符串的 Agent/Workflow 不取得 writer。取得 writer 后，非空 frame 刷新 idle deadline；超时只让位、不取消 Run，后续再有可公开 frame 时从队尾恢复。Run terminal 会在排完自身 pending frame 后立即让位，公开 response 则等待全部 scheduler producer terminal 且 pending 排空。所有事件先经过所属 Agent Event Output 或 Workflow Event Output；reasoning 与 assistant text 使用`start / delta / finish`，其他非空投影作为 atomic frame。`max_batch_kb`与`send_interval_seconds`只控制客户端发送批次，producer 提交不等待 scheduler 消费。

## 拦截消息

【系统 / 拦截消息】提供一个独立于 Workflow 的 Shell 入站开关。开启后，合法 Chat Completions 请求完成鉴权、
基础 OpenAI 字段检查后立即短路，不捕获 Workflow 配置快照，不装配 Agent，也不创建 Run。
调用方按原 `stream` 模式收到 OpenAI-compatible 的“消息已拦截”回复，token usage 为零。

页面通过 management-only API 显示进程内最新一条请求原文。开关持久化，正文仅保存在当前进程；开关从关闭变为开启或服务重启时清空原文。

## 运行边界

- Workflow 保存一份 current Graph；草稿保存设置 `enabled=false`，正式保存通过完整校验后设置 `enabled=true`；
- Main Agent 新建与普通更新保存 `enabled=false` 草稿；`PUT /agent-shell/api/main-agents/{id}/publish` 通过完整校验后保存 `enabled=true`，其中 `is_model_entry=true` 的正式 Main Agent 可由 `/compat/openai/v1` 启动；
- `enabled=true` 且 `is_model_entry=true` 的 Workflow 可由 `/compat/openai/v1` 启动；任何 enabled Workflow 都可被其他 Run 调用；
- 每次请求执行一次完整官方Run；Main Agent Assistant ID由其UUID稳定派生，Workflow Assistant ID使用Workflow UUID，Thread和Run ID使用官方身份；
- 独立Graph调用通过`Runtime.context.agent_runs`或`workflow_runs`的`start/check/list/join/cancel`使用公共Agent Server SDK；每次调用创建或明确续接Thread并创建新Run。Command只返回`update + goto`，多个goto目标和循环按LangGraph Super-step语义执行；
- 每个被调用 Run 使用自己的 Event Output projector，并把已投影事件提交给同一个 Lifecycle response scheduler；scheduler 只按 Run identity 隔离输出，不建立静态运行角色；
- 图不完整、引用失效、Agent 装配失败或 Provider 失败时，本次请求返回稳定错误码、基础分类消息和关联 identity；
- 日志中心展示系统事件和结构化运行失败诊断，运行异常自动尝试保存 traceback 附件；
- Assistant、Thread、Run 与 State 可通过同端口的 LangGraph Dev 官方 API 读取；官方 route 使用管理密码。`/agent-shell/api/workflow-lifecycles` 通过公共 Thread/Run API 聚合本次请求的全部 Run，并提供 Graph、latest State 和 State history 读取。

## API Key 与状态

API Key 是 write-only 设置，用于 `/compat/openai/v1/*`；管理密码用于管理台、除 Health 外的 `/agent-shell/api/*`，以及 LangGraph Agent Server 官方资源路径。清除 API Key 后推理 API 不可用。
API Server启停与model catalog使用当前Repository入口配置；完整repository validation用于管理诊断，单次Chat请求只运行所选Main Agent或Workflow root Graph及其显式启动的独立Run。

API Key 是个人实例的受信任执行凭据。推理失败响应只返回稳定错误码、基础分类消息和关联 identity；Provider 正文、本机路径等运行细节只进入 management-only 的运行诊断，其 local exception-detail attachment 保留完整 traceback。内容投影遵循[数据分类与错误披露](../security-and-deployment.md#数据分类与错误披露)。
