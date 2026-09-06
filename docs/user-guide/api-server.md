# API Server

首页使用【服务入口】和【API 端点】两张 Card 展示当前实例地址、LangGraph 官方路径族、诊断端点与认证边界。OpenAI-compatible Base URL 是 `<origin>/compat/openai/v1`；Agent Shell API Base URL 是 `<origin>/agent-shell/api`。API Server 运行状态与启动、停止按钮位于管理台 navbar，在所有页面可见；
API Key 位于【系统 / 系统配置】的 API Server Card，由 `PUT /agent-shell/api/api-server` 保存。

## 接口

```http
GET /compat/openai/v1/models
Authorization: Bearer <API Key>
```

返回OpenAI-compatible list；`data[].id`来自`is_model_entry=true`的Main Agent name，以及`enabled=true`且`is_model_entry=true`的Workflow name。

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

请求按model name捕获一次配置快照。Main Agent入口物化完整Deep Agents graph；Workflow入口物化current Start/Command/End control Graph。两者都由稳定Assistant启动官方Thread/Run并由LangGraph Dev Worker执行。Command需要AI时通过`runtime.context.agent_runs`启动独立Main Agent Thread/Run。官方ProtocolEvent由对应Graph的Agent或Workflow Event Output、Lifecycle Response Scheduler和OpenAI response writer消费。

Agent Shell 校验 OpenAI-compatible 消息结构、内容来源、MIME 与 Base64 格式，不设置项目级请求体、消息条数、content block 数量或解码媒体字节上限。实际能力仍受 Provider、内存、磁盘和网络影响。

Workflow可执行Node class为Start、Command和End，只有一种Control Edge。canvas Start/End直接映射LangGraph官方`START/END`；Start Edge映射`StateGraph.add_edge()`，Command outgoing Edge只声明允许的dynamic destination。Command脚本读取只含`shared_vars`的Workflow State和Runtime Context，直接返回官方`Command(update, goto)`。规范化后的`messages[]`保存在本次Lifecycle的Server Store namespace；Workflow不消费它。Main Agent只有已装配的`before_agent`/`abefore_agent`Middleware决定如何选择输入并写入AgentState。

每个 Workflow 显式配置 `durability` 与 `on_disconnect`。实例级 `recursion_limit`、可选 `max_concurrency` 和 `n_jobs_per_worker` 位于【系统 / 系统配置 / 限制策略】，使用 LangGraph/LangChain 官方字段；`max_concurrency` 留空时不向运行配置传值。全部 Workflow Run 的 Thread、checkpoint、State 与 history 由 LangGraph Dev 官方运行时拥有。

每个 Workflow 独立保存 `on_disconnect=cancel|continue`，默认 `cancel`。客户端在 Run 完成前断开时，只读取本次请求入口 Workflow 的设置：`cancel` 取消同一 Lifecycle 的全部 active Run，`continue` 让全部 Run 在后台继续。其他 Run 的成功、失败或取消不会触发隐式连锁取消，调用关系也不形成 Parent/Child 权限。

作为请求入口的 Workflow 通过可空 `response_stream_scheduling_id` 引用【工作流组件】中的 Response Stream Scheduling 配置。未装配时使用内置默认；装配后从当前请求冻结的 Configuration Repository 快照读取 request/node invocation 输出原子、闲置让位秒数、批次软大小和最小发送间隔。组件只调度 Agent/Workflow Event Output 已批准的文本，不拥有事件可见性或修饰规则。

`stream=false` 返回标准 `chat.completion` JSON。`stream=true` 返回 `chat.completion.chunk` SSE，并以 `data: [DONE]` 结束。一次 OpenAI response 创建一个 Lifecycle Response Scheduler，各 participating Run 的 Event Output producer 将已投影文本和内部调度信号提交给它；任一时刻只有一个 lane 可以向 append-only assistant 字符串写入。两种模式消费同一 frame sequence，因此流式 content chunk 拼接结果与非流式 message content 一致。

响应流策略作用于整个 Lifecycle。请求入口 Workflow 的组件引用随启动快照冻结；由该 Run 直接或间接启动的 Run 共用本次 response scheduler。策略只配置 request/node invocation 输出原子、空闲让位时间、批次软大小和最小发送间隔。所有规范化事件先经过所属 Agent Event Output 或 Workflow Event Output；脚本返回空字符串时不进入响应且不刷新writer lease，返回非空字符串时才作为公开文本交给scheduler排队。无正文的content/request/Node terminal控制边界仍可关闭segment或释放atom。reasoning与assistant text使用统一的additive `start / delta / end`投影：流式delta实时进入脚本，非流式完整正文机械展开为单个delta，已有真实delta时finish snapshot不重复正文。Tool call与terminal outcome分别投影，再作为不可插队的原子项输出；`message-finish`不代表关联Tool已经完成，慢Tool等待超过空闲时间后只释放当前位置。同一invocation的下一次model request开始或Node terminal是前一个request的确定结束边界，不等待idle timeout才让位。

## 拦截消息

【系统 / 拦截消息】提供一个独立于 Workflow 的 Shell 入站开关。开启后，合法 Chat Completions 请求完成鉴权、
基础 OpenAI 字段检查后立即短路，不捕获 Workflow 配置快照，不装配 Agent，也不创建 Run。
调用方按原 `stream` 模式收到 OpenAI-compatible 的“消息已拦截”回复，token usage 为零。

页面通过 management-only API 显示进程内最新一条请求原文。开关持久化，正文仅保存在当前进程；开关从关闭变为开启或服务重启时清空原文。

## 运行边界

- Workflow 保存一份 current Graph；草稿保存设置 `enabled=false`，正式保存通过完整校验后设置 `enabled=true`；
- `enabled=true` 且 `is_model_entry=true` 的 Workflow 可由 `/compat/openai/v1` 启动；任何 enabled Workflow 都可被其他 Run 调用；
- 每次请求执行一次完整官方 Run；Assistant ID 使用 Workflow UUID，Thread 和 Run ID 使用官方身份，Node 从 `Runtime.execution_info.run_id` 读取同一个 Run ID；
- 独立Graph调用通过`Runtime.context.agent_runs`或`workflow_runs`的`start/check/list/join/cancel`使用公共Agent Server SDK；每次调用创建或明确续接Thread并创建新Run。Command只返回`update + goto`，多个goto目标和循环按LangGraph Super-step语义执行；
- 每个被调用 Run 使用自己的 Event Output projector，并把已投影事件提交给同一个 Lifecycle response scheduler；scheduler 只按 Run identity 隔离输出，不建立静态运行角色；
- 图不完整、引用失效、Agent 装配失败或 Provider 失败时，本次请求返回对应错误；
- 日志中心展示系统事件和结构化运行失败诊断，运行异常自动尝试保存 traceback 附件；
- Assistant、Thread、Run 与 State 可通过同端口的 LangGraph Dev 官方 API 读取；官方 route 使用管理密码。`/agent-shell/api/workflow-lifecycles` 通过公共 Thread/Run API 聚合本次请求的全部 Run，并提供 Graph、latest State 和 State history 读取。

## API Key 与状态

API Key 是 write-only 设置，用于 `/compat/openai/v1/*`；管理密码用于管理台、除 Health 外的 `/agent-shell/api/*`，以及 LangGraph Agent Server 官方资源路径。清除 API Key 后推理 API 不可用。
API Server 启停不扫描未被 Workflow 引用的 Main Agent；完整 repository validation 只用于管理诊断，单次 Chat 请求只解析所选 Workflow 的 current Graph 和可达装配。

普通 API response、DOM 和 log summary 仅提供脱敏后的公开字段；management-only 的 local exception-detail attachment 保留完整排错信息。
