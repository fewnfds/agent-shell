# 日志中心与 Workflow 观测

## 日志中心

【系统 / 日志中心】只合并两类运维记录（management-only，需要管理鉴权；相关系统设置见[数据、文件与系统设置](system-management.md)）：

- 系统日志：服务、配置、安全和管理请求事件；
- 运行诊断：Workflow、Agent、background task、持久化或观测链路的失败摘要。

运行诊断使用 `diagnostic_id`，并按可用范围关联 `request_id`、`lifecycle_id`、`run_id`、仅在启用 Checkpointer 时存在的 `thread_id`、parent Workflow、
`subject_kind/id/name`、Workflow Node、`node_invocation_id` 和 `exception_type`；没有值的字段不存储。正常完成的 Run 不生成运行诊断。

页面提供时间、来源、级别和全文筛选、摘要查看、按筛选条件批量删除，以及超大 JSON 条目下载。系统日志按文件大小保留（默认 `5 MiB`，最小 `1 MiB`），运行诊断按条数保留（默认 `20` 条，最小 `1` 条）；两者只清理自己拥有的日志数据。

日志中心不保存 Workflow Lifecycle、Run 历史、Graph State、checkpoint 或 Store 数据，也不负责这些核心运行数据的保留与删除。一次 Lifecycle 的完整输入、多 Run 结构和节点执行历史不能从日志中心还原。

## 异常详情

运行异常产生诊断时，系统同时尝试把完整 Python exception chain 和 traceback 保存到 `data/logs/diagnostics/diagnostic-{diagnostic_id}.log`，并从对应诊断行下载；正常完成不会产生附件。附件写入失败不会阻塞原运行失败边界，
对应诊断以 `detail_available=false` 表示没有可下载详情。

exception detail 可能包含请求内容、Provider response、credential、host path 和自定义代码信息；普通 API response、DOM、system log 和 diagnostic summary 仍按脱敏边界不回显这些内容，只有 management-only exception-detail attachment 可由维护者下载查看。删除 diagnostic 或降低 diagnostic retention count 时，
对应附件一起删除；附件不具有独立于诊断记录的生命周期。

Provider 有明确 4xx/5xx 状态时，普通 HTTP 调用方收到该状态和固定的 `provider_request_failed` 安全说明；SSE 已建立为 200 时则在最终 `chat.completion.chunk` 中返回 `finish_reason="error"` 和 `error.code="provider_request_failed"`，随后发送 `[DONE]`。原始 Provider 异常仍作为 cause 进入上述完整异常链；实例维护者从日志中心对应的运行诊断行下载附件，才能查看网关返回的真实内容。

## 运行监控

【系统 / 运行监控】以一次顶层请求的 Lifecycle 聚合 root Workflow Run 和全部 background Workflow Run，属于需要管理鉴权的实例级功能。Lifecycle 目录提供搜索、分页、单项删除和按当前服务端搜索条件批量删除；目录展示 parent Workflow、创建时间、状态、Run 数量、失败数、Token 用量和本次 Lifecycle 是否启用监控采集。启用采集的记录提供【监控】入口；关闭采集的记录保留禁用入口和明确说明，避免发送必然失败的详情请求。

Lifecycle 监控详情使用 `/system/workflow-lifecycles/{lifecycle_id}/monitoring?run_id={run_id}`。左侧 Run 索引只按 snapshot 返回的 roots 与 parent/child relationship 显示层级；未指定有效 `run_id` 时选择 Lifecycle 的 root Run。选择 Run 后，右侧用只读 Vue Flow 显示该 Run 保存的 frozen Graph，并按 Node summary 展示 attempt 数量和状态；只有 `status_counts.running > 0` 的 Node 使用运行中强调，文字与数字同时表达状态。画布保留 frozen Node 位置与 viewport，关闭编辑、连线和 Edge 动画；空文档不会自动补画 Start/End。Graph 或 Node 资源的 `partial|unavailable` 只在 Graph 区域呈现，Run 索引仍可继续选择。

详情页在进入页面和选择 Run 时通过普通 HTTP GET 读取持久化 snapshot/resource；重新载入页面可取得之后写入的事实。Management-only 运行监控接口还可按 Lifecycle、Workflow 或单个 Run 读取 snapshot，并按 Run 读取 Node attempt、raw ProtocolEvent 及其 compact direct origin、Run 级 Model Request、Command observation、latest persisted State 与 exact completed Agent invocation artifact。请求之间没有服务端会话、自动轮询、SSE、WebSocket 或统一 change feed。通用 Lifecycle detail/events、single Run detail 和 Lifecycle/Run download 接口返回 `503 runtime_monitoring_read_model_unavailable`；运行归档没有读取入口。

Workflow scope 只先选择本 Lifecycle 中 `workflow_id` 精确匹配的 Run，再沿 Registry `parent_run_id` 包含 descendants；Run forest 也只表达这条 parent/child 关系。Node、Agent、Tool、Edge 或跨 Run 因果不会从 event namespace、时间关系或 Graph 路径推演。每个资源都返回自己的 `availability`，局部 `partial|unavailable` 不会遮蔽其他可读事实。

### 持久化事实

Runtime Registry 是 Lifecycle 与 Workflow Run 控制事实的权威 owner。每个 root/background Run 使用独立 `run_id`，并保存 parent/background relationship、Workflow identity、状态、起止时间、终止原因、错误码和 usage。Registry 注册、开始或终态提交失败属于运行控制故障，不能作为可选观测写入吞掉。

启用采集的每个 Run 同时保存以下监控事实：

- Run 注册时保存本次实际执行的不可变 `WorkflowGraphDocumentV1` 与 document SHA；之后修改或删除 current Workflow 不改变这份 Graph；
- Canvas Agent/Command Node wrapper 直接保存 LangGraph `Runtime.execution_info` 提供的 `task_id`、1-indexed `node_attempt` 与可空 `node_first_attempt_time`，并记录 `running|completed|failed|cancelled`。同一 invocation 的 retry 沿用 task ID 并增加 attempt；循环或 fan-out invocation 使用不同 task ID。终态 Run 遗留的 `running` row 会收敛为 `incomplete|interrupted` 并令 Node partition 为 `partial`；
- `RunExecution` 在 v3 transformer 之后的 direct-consumer 边界保存本次实际产生的 raw `ProtocolEvent` envelope 与 capture time，并复用同一轮已经用于 Event Output 的 resolver 结果，同行保存 `source_type`、Workflow Node、Node invocation、Main Agent 和 Subagent 五项 compact direct origin。无法直接证明 Node 或 Agent 归属时，对应 ID 保持空字符串，事件仍属于 Run；监控不会额外声明 `values`、`updates`、`tasks`、`debug` 等 stream mode，也不会恢复 transformer 已抑制的事件；
- 每次 ChatModel 调用在 LangChain `on_chat_model_start` 边界保存 message batches、绑定 Tool schema、invocation parameters、options、tags 和 metadata，并在 `on_llm_end` 或 `on_llm_error` 保存终态、usage 或安全错误类型。该边界位于 middleware 处理和模型绑定之后、Provider adapter 最终 HTTP 序列化之前；记录属于 Workflow Run，不把 callback metadata 解析成 Canvas Node、Main Agent 或 Subagent owner；
- Command Node 按 invocation/attempt 保存 `started` 与 `completed|failed|cancelled` 外部观察。成功记录经过校验的 `{activate, dispatch, update}`，失败只记录稳定错误码，不保存脚本源码、locals、MCP session 或完整输入 State。

Graph、Node、ProtocolEvent、Model Request 和 Command 五个分区分别具有 `capturing`、`available`、`partial` 或 `not_applicable` 状态。任一可选 writer 失败只停止该分区后续采集、标记 `partial` 并写一条不含业务正文的运行诊断，不改变 LangGraph 正式结果。Run 已进入终态而分区仍处于 `capturing` 时，读取接口立即按 `partial` 投影；Lifecycle 状态变化或服务启动恢复会幂等地持久化该收敛结果。Graph 已成功冻结以及本来不适用的分区保持原状态。

Workflow Run 只有在自己的 Workflow 引用 Checkpointer Component 时才拥有 `checkpoint_thread_id`，并由共享的官方 LangGraph `AsyncSqliteSaver` 写入 Checkpoint。Parent 与 background child 独立读取各自冻结配置。监控通过官方 Checkpointer `aget_tuple()` 读取 latest persisted root State；没有 Checkpointer 时明确显示 `not_enabled`。当前不提供 State history、修改、Resume、time travel 或灾难恢复入口。

完成的 Agent invocation artifact 已由 Lifecycle Store 保存时，监控先验证对应 Node attempt、frozen Agent Node 与 Agent UUID，再使用固定 Lifecycle/Run namespace 和 invocation key 通过官方 Store `aget()` 精确读取。接口不扫描 namespace，也不开放 Lifecycle input、background task、filesystem route 或任意 Store browser。

### 后端读取接口

- `GET /api/workflow-lifecycles/{lifecycle_id}/monitoring/snapshot`：Lifecycle scope；可选且互斥的 `workflow_id` 或 `run_id` 选择另两种 scope；
- `GET .../monitoring/runs/{run_id}/graph`：frozen Workflow Graph；
- `GET .../monitoring/runs/{run_id}/nodes` 与 `/nodes/{node_id}/attempts`：Node 汇总和 attempt 分页；
- `GET .../monitoring/runs/{run_id}/protocol-events`：按 `after_sequence` 续读 raw envelope 及 compact direct origin；可选 `method`、`node_id`，或同时使用 `node_id` + `invocation_id` 精确筛选；
- `GET .../monitoring/runs/{run_id}/model-requests`：Run 级 Model Request 分页；
- `GET .../monitoring/runs/{run_id}/command-observations`：按 `after_sequence` 续读 Command 外部观察；
- `GET .../monitoring/runs/{run_id}/state`：latest persisted root State；
- `GET .../monitoring/runs/{run_id}/agent-invocations/{invocation_id}`：exact completed Agent artifact。

捕获关闭的 Lifecycle 返回 `409 runtime_monitoring_disabled`；不存在的 Lifecycle、Run、Workflow scope、frozen Node 或 invocation 返回对应 404；只提供 `invocation_id` 而未提供 `node_id` 时返回 `422 runtime_monitoring_protocol_selector_invalid`；Registry/snapshot 整体不可读返回 503。独立资源读取失败返回 `200` 和 `availability=unavailable`，允许其他区域继续显示并在下一轮重试。Protocol/Command 用响应的 `next_after_sequence` 续读；Graph、Run、Node、Model、State 与 Agent artifact 重新读取当前 snapshot/page。

### 保留与删除

【系统 / 系统配置】的 `runtime_monitoring_retention_lifecycles` 默认值为 `20`、最小值为 `0`，没有产品最大值。创建 Lifecycle 时以当时的值是否大于 `0` 冻结 `monitoring_capture_enabled`；运行中修改设置不会改变该 Lifecycle 的采集 profile。全局保留数量始终使用最新设置，因此降低数值会立即收敛已经完整终止的数据。

Lifecycle 只有在 root Run、全部 child Run 和全部 background task 都进入终态后才取得 `fully_terminal_at`。活动 Lifecycle 不计入保留数量；完整终态的数据按 `(fully_terminal_at, lifecycle_id)` 保留最近 N 个，因此创建较早但结束较晚的长任务按实际结束顺序参与保留。服务启动时先把遗留 active Run 和失去进程 owner 的 background task 归一为 `interrupted`，再判断完整终态并执行保留策略。

值为 `0` 时，新 Lifecycle 不写监控事实，但 Registry、Lifecycle input 和 background task 等运行必需控制数据仍服务到完整终态，随后自动清理。自动保留清理删除该 Lifecycle 的 Registry、监控事实、官方 Store input/task/invocation/filesystem route，以及所有非空 `checkpoint_thread_id` 对应的官方 checkpoint；它不删除日志中心诊断以及任何运行中写入硬盘的用户文件或目录。

单项删除和批量删除同样拒绝 active Lifecycle。Lifecycle 动态模式创建的 `lifecycle-{lifecycle_id}` 目录及其内容属于用户文件，运行监控不登记、保留计数或删除它们；用户通过文件管理入口或宿主文件系统自行管理。批量删除作用于服务端完整匹配集，跳过 active Lifecycle；空搜索条件匹配全部目录记录。

### 敏感内容

启用采集后，frozen Graph、Node/Command metadata、ProtocolEvent、Model Request、Checkpoint State 和 Agent invocation artifact 可以包含 prompt、用户消息、Tool schema/payload、State、路径以及其他运行材料。ProtocolEvent、Model Request 与 State 读取投影的 JSON 转换排除 Secret 类型，并脱敏明确的 credential、API Key、token 和 password 字段；Command 的已校验外部结果与 Agent 的 OpenAI message artifact 保留普通业务内容。平台不能识别用户主动写入普通文本或自定义对象表示中的任意密钥。`agent-shell.env` 是配置 secret 的唯一权威存储，监控 writer 不读取该配置文件。所有读取接口都需要管理鉴权。运行归档下载没有入口；未来分享任何由这些事实生成的归档前需人工检查自由文本。

## LangSmith

LangSmith 是可选的外部 trace 服务，可查看 prompt、模型输出、工具调用和 LangChain/LangGraph Run/Trace 层级；配置入口见[数据、文件与系统设置](system-management.md)。
应用日志与 trace 是不同的观测面，可通过 request、Lifecycle、Run 或 trace identity 关联，但不互相替代。
