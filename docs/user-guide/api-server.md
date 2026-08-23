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

请求只按父图 Workflow name 捕获一次配置快照，从同一快照读取当前 Graph 和画布 Agent 节点引用，再递归构造 Main Agent、Subagent、各自 Filesystem、权限、Middleware、组件和 Provider secret view。构造完成后关闭请求配置快照，
运行阶段使用该请求开始时捕获的配置快照。

Chat 请求体、content block、输入媒体单项/合计和输出媒体边界由【系统 / 系统配置】的限制策略决定；
`GET /api/system/runtime-policy` 返回后端当前值、默认值、最小值和可配置字段，前端不复制隐藏上限。策略只有后端返回的正数最小值约束，没有额外产品最大值，实际仍受 Provider、
内存、磁盘和网络能力影响。

当前可执行 Node class 为 Start、Agent、Command、任务分发和 End，Edge class 为 normal、branch 与 dispatch；一张图可以包含多个 Agent node，并可串联、
fan-out、fan-in 或形成 LangGraph 支持的循环。画布 Start/End 直接映射 LangGraph 官方 `START/END`，normal edge 映射 `StateGraph.add_edge()`；Command 脚本读取完整 Workflow State 和 Runtime Context，返回 State partial update 与零个、一个或多个分支 key；候选 key 直接由画布具名 Branch Edge 声明，runtime 将非空激活结果映射为 `Command(update=..., goto=[...])`。任务分发脚本从 State/Context 生成具名 JSON 任务，runtime 将每项映射为 LangGraph `Send`，并把 `workflow_task` 放入目标 Agent 的私有 State。Start 不注入客户端消息。规范化后的 `messages[]` 保存在 Lifecycle Store；Runtime Context 只携带定位输入所需的 lifecycle/run/invocation 身份。只有已装配的 `before_agent`/`abefore_agent` Middleware 决定如何读取、切割并写入 Agent state。

每个 Workflow 显式配置 `recursion_limit`、`execution_timeout_seconds` 和 `max_concurrency`。默认值分别是 `1,000,000`、`1,200` 秒和 `100`；这些运行值只有正数约束，没有额外的产品上限。`recursion_limit` 与 `max_concurrency` 传给 LangGraph Runnable config；`execution_timeout_seconds` 限制单个 parent 或 child Run 的实际执行时间，不包含生成器停在 `yield` 等待慢速调用方消费已生成 SSE 文本的时间。后台 Agent 继承启动它的父 Workflow 配置，后台 Workflow 使用自己的配置。

`stream=false` 返回标准 `chat.completion` JSON。`stream=true` 返回 `chat.completion.chunk` SSE，并以 `data: [DONE]` 结束。两种模式都消费同一次 LangGraph v3 事件流，并按 Workflow node 对应 Main Agent 的 `agent-event-output` Python 扩展中的同步 `output(event)` 渲染；扩展可自行返回空字符串过滤事件。Workflow-owned 事件由 Workflow 可选绑定的 `workflow-event-output` 扩展处理。两类扩展都接收稳定 dict 并返回公开响应文本。

## 拦截消息

【系统 / 拦截消息】提供一个独立于 Workflow 的 Shell 入站开关。开启后，合法 Chat Completions 请求完成鉴权、
请求体大小限制和基础 OpenAI 字段检查（含 `max_initial_messages` 数量上限）后立即短路，不捕获 Workflow 配置快照，不装配 Agent，也不创建 checkpoint。
调用方按原 `stream` 模式收到 OpenAI-compatible 的“消息已拦截”回复，token usage 为零。

页面通过 management-only API 显示进程内最新一条请求原文。开关持久化，正文仅保存在当前进程；开关从关闭变为开启或服务重启时清空原文。

## 运行边界

- Workflow 保存一份当前图；草稿保存设置 `enabled=false`，正式保存通过完整校验后设置 `enabled=true`；
- parent/child 是同一 Workflow 实体的使用角色，`/v1` 入口启动 parent Workflow；
- 每次请求执行一次完整运行；每个 Workflow Run 建立独立 thread 并使用官方持久 checkpointer；
- 后台 Agent/Workflow Run 通过 Runtime Context 的 `background_runs` 命令启动和查询；Task Dispatcher 在请求内生成动态 worker，多个 normal 出边、一次激活的多个 branch 目标和多个 Send task 按 LangGraph super-step 语义执行；
- 图不完整、引用失效、Agent 装配失败或 Provider 失败时，本次请求返回对应错误；
- 日志中心展示系统事件和结构化运行失败诊断，运行异常自动尝试保存 traceback 附件；
- management-only `/api/workflow-lifecycles` 提供运行历史列表、Lifecycle/Run 详情、结构事件分页、诊断包下载和显式删除。列表使用 `page/page_size/query` 后端分页；详情和导出提供结构记录、Checkpoint/Store 摘要与关联诊断。删除在 parent 和后台任务进入终态后执行，并可清理受管动态目录。

## API Key 与状态

API Key 是 write-only 设置，用于 `/v1/*`；管理密码用于管理台和 `/api/*`。清除 API Key 后推理 API 不可用。
API Server 启停不扫描未被 Workflow 引用的 Main Agent；完整 repository validation 只用于管理诊断，单次 Chat 请求只解析所选 Workflow 的当前图和可达装配。

普通 API、DOM 和日志摘要仅提供脱敏后的公开字段；management-only 的本地异常详情附件保留完整排错信息。
