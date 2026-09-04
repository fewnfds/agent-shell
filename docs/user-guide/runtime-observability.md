# 日志中心与 Workflow 观测

## 日志中心

【系统 / 日志中心】只合并两类运维记录（management-only，需要管理鉴权；相关系统设置见[数据、文件与系统设置](system-management.md)）：

- 系统日志：服务、配置、安全和管理请求事件；
- 运行诊断：Workflow、Agent、跨 Workflow 调用、持久化或观测链路的失败摘要。

运行诊断使用 `diagnostic_id`，并按可用范围关联 `request_id`、`lifecycle_id`、`run_id`、`thread_id`、Workflow、
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

当前 LangGraph Dev 执行迁移期间，Server-managed 请求入口 Run 与被调用 Run 尚未写入 application Runtime Registry，因此不会出现在【系统 / 运行监控】目录；这些 Run 的 Assistant、Thread、Run 与 State 通过同端口官方 API 读取。以下页面和归档行为适用于 Registry 中已经登记的 Lifecycle/Run，Management 读取面将在 Lifecycle/Monitoring 阶段改为组合官方对象。

【系统 / 运行监控】以一次请求入口的 Lifecycle 聚合入口 Workflow Run 和全部被调用 Workflow Run，属于需要管理鉴权的实例级功能。Lifecycle 目录提供搜索、分页、单项删除和按当前服务端搜索条件批量删除；目录展示入口 Workflow、创建时间、状态、Run 数量、失败数、Token 用量和本次 Lifecycle 是否启用监控采集。启用采集的记录提供【监控】和【下载】入口；关闭采集的记录保留带原因的禁用操作，避免发送必然失败的详情或下载请求。

Lifecycle 监控详情使用 `/system/workflow-lifecycles/{lifecycle_id}/monitoring`。页面范围可选整个 Lifecycle、一个 Workflow 及其后代 Run，或单个 Run；Workflow 后代关系由后端 Registry 计算，浏览器只显示返回结果。选择与详情状态通过 `scope`、`workflow_id`、`run_id`、`node_id` 和 `view` query 保存；未指定有效 Run 时选择当前范围内的 Lifecycle root Run 或首个 Run。左侧 Run 索引只按 snapshot 返回的 roots 与 caller/spawned relationship 显示层级。中间用只读 Vue Flow 显示所选 Run 保存的 frozen Graph，并按 Node summary 展示 attempt 数量和状态；只有 `status_counts.running > 0` 的 Node 使用运行中强调，文字与数字同时表达状态。画布保留 frozen Node 位置与 viewport，关闭编辑、连线和 Edge 动画；空文档不会自动补画 Start/End。

点击 Graph Node 或用键盘激活 Node，会在共用详情区读取当前 Lifecycle + Run + frozen Node 的持久化 attempt 分页。详情显示后端提供的 invocation ID、1-indexed attempt、sequence、开始/结束时间、状态和稳定错误码。Agent Node 可以选择一次 invocation，查看 exact completed artifact，以及 compact direct origin 明确属于该 Node + invocation 的已记录 ProtocolEvent；消息正文和标准文本 content block 直接呈现，其他结构始终可展开 raw JSON。Command Node 显示该 Node 的 `started|completed|failed|cancelled` observation，以及成功时经过校验的 `activate`、`dispatch`、`update` 外部结果，不把它们解释成 Edge 已激活结论。前端不根据时间、事件、namespace 或 Graph 路径推断 retry、激活或跨 Run 因果。

所选 Run 的【事件】【模型】【State】入口使用同一个详情区。事件按 Run 显示 raw ProtocolEvent；模型请求按页显示状态、时间、usage 与原始请求；State 显示 latest persisted root Checkpoint 的 namespace、持久化时间、step、pending write 数量、channel 名称和完整 State。State 只在打开或手动刷新时读取，以持久化时间说明它与当前执行可能存在的间隔。Graph 标题区的【下载此 Run】下载当前所选 Run，不改变 scope、详情或轮询状态。选择历史 Agent invocation 后，后台刷新保留该选择；Node 出现更新的 attempt 时由【查看最新】按钮决定是否跳转。事件列表只在读者仍位于底部并保持【跟随最新】时自动滚动。

活动 Lifecycle 在页面可见时约每两秒通过普通 HTTP GET 重新读取完整 Lifecycle snapshot、当前 scope snapshot 和已打开的轻量资源；frozen Graph 只在选择 Run 时读取，State 只手动刷新。页面隐藏时暂停，恢复可见时立即刷新；Lifecycle 完全终态时完成当前最后一轮资源读取并切为静态结果。一次刷新失败保留上一份成功数据并按普通间隔重试；Graph、Node summary、Node attempt、Agent artifact/event、Command、Model、State 各自在对应区域呈现 `partial|unavailable` 或请求错误，不遮蔽其他成功区域。请求之间没有服务端会话、SSE、WebSocket 或统一 change feed。

Workflow scope 只先选择本 Lifecycle 中 `workflow_id` 精确匹配的 Run，再沿 Registry `caller_run_id` 包含 descendants；Run forest 也只表达 `caller_run_id -> spawned_run_id` 关系。Node、Agent、Tool、Edge 或跨 Run 因果不会从 event namespace、时间关系或 Graph 路径推演。scope 外的 caller 使当前 Run 成为局部视图 root，不构成 orphan。每个资源都返回自己的 `availability`，局部 `partial|unavailable` 不会遮蔽其他可读事实。

### 持久化事实

Runtime Registry 是 Lifecycle 与 Workflow Run 控制事实的当前 owner。每个入口或被调用 Run 使用独立 `run_id`，并保存可空 `caller_run_id`、可空 `operation_id`、Workflow identity、状态、起止时间、终止原因、错误码和 usage。Registry 注册、开始或终态提交失败属于运行控制故障，不能作为可选观测写入吞掉。

启用采集的每个 Run 同时保存以下监控事实：

- Run 注册时保存本次实际执行的不可变 `WorkflowGraphDocumentV1` 与 document SHA；之后修改或删除 current Workflow 不改变这份 Graph；
- Canvas Agent/Command Node wrapper 直接保存 LangGraph `Runtime.execution_info` 提供的 `task_id`、1-indexed `node_attempt` 与可空 `node_first_attempt_time`，并记录 `running|completed|failed|cancelled`。同一 invocation 的 retry 沿用 task ID 并增加 attempt；循环或 fan-out invocation 使用不同 task ID。终态 Run 遗留的 `running` row 会收敛为 `incomplete|interrupted` 并令 Node partition 为 `partial`；
- `RunExecution` 在 v3 transformer 之后的 direct-consumer 边界保存本次实际产生的 raw `ProtocolEvent` envelope 与 capture time，并复用同一轮已经用于 Event Output 的 resolver 结果，同行保存 `source_type`、Workflow Node、Node invocation、Main Agent 和 Subagent 五项 compact direct origin。无法直接证明 Node 或 Agent 归属时，对应 ID 保持空字符串，事件仍属于 Run；监控不会额外声明 `values`、`updates`、`tasks`、`debug` 等 stream mode，也不会恢复 transformer 已抑制的事件；
- 每次 ChatModel 调用在 LangChain `on_chat_model_start` 边界保存 message batches、绑定 Tool schema、invocation parameters、options、tags 和 metadata，并在 `on_llm_end` 或 `on_llm_error` 保存终态、usage 或安全错误类型。该边界位于 middleware 处理和模型绑定之后、Provider adapter 最终 HTTP 序列化之前；记录属于 Workflow Run，不把 callback metadata 解析成 Canvas Node、Main Agent 或 Subagent owner；
- Command Node 按 invocation/attempt 保存 `started` 与 `completed|failed|cancelled` 外部观察。成功记录经过校验的 `{activate, dispatch, update}`，失败只记录稳定错误码，不保存脚本源码、locals、MCP session 或完整输入 State。

Graph、Node、ProtocolEvent、Model Request 和 Command 五个分区分别具有 `capturing`、`available`、`partial` 或 `not_applicable` 状态。任一可选 writer 失败只停止该分区后续采集、标记 `partial` 并写一条不含业务正文的运行诊断，不改变 LangGraph 正式结果。Run 已进入终态而分区仍处于 `capturing` 时，读取接口立即按 `partial` 投影；Lifecycle 状态变化或服务启动恢复会幂等地持久化该收敛结果。Graph 已成功冻结以及本来不适用的分区保持原状态。

ProtocolEvent 先进入本 Run 的有序内存缓冲，再由 application SQLite worker 把当时已排队的记录作为一个事务写入。正常完成、失败和取消都会先排空已经接收的记录，再提交 Run 终态；应用正常关闭也会排空仍登记的 writer。运行中的读取只显示已经提交到 SQLite 的记录，因此可以短暂落后于正在消费的 stream。进程被强制终止时，尚在内存中的可选观测记录可能丢失；恢复边界会把无法证明完整的分区呈现为 `partial`，不会伪装成完整历史。

Server-managed Workflow Run 的 Thread、checkpoint、State 与 history 由 LangGraph Dev runtime 拥有。应用监控中的 `checkpoint_thread_id` 与 latest State 读取面将在 persistence/monitoring 阶段改为公共 Thread API；当前不提供 State 修改、Resume、time travel 或灾难恢复入口。

完成的 Agent invocation artifact 已由 Lifecycle Store 保存时，监控先验证对应 Node attempt、frozen Agent Node 与 Agent UUID，再使用固定 Lifecycle/Run namespace 和 invocation key 通过官方 Store `aget()` 精确读取。接口不扫描 namespace，也不开放 Lifecycle input、filesystem route 或任意 Store browser。

### 后端读取接口

- `GET /api/workflow-lifecycles/{lifecycle_id}/monitoring/snapshot`：Lifecycle scope；可选且互斥的 `workflow_id` 或 `run_id` 选择另两种 scope；
- `GET .../monitoring/runs/{run_id}/graph`：frozen Workflow Graph；
- `GET .../monitoring/runs/{run_id}/nodes` 与 `/nodes/{node_id}/attempts`：Node 汇总和 attempt 分页；
- `GET .../monitoring/runs/{run_id}/protocol-events`：按 `after_sequence` 续读 raw envelope 及 compact direct origin；可选 `method`、`node_id`，或同时使用 `node_id` + `invocation_id` 精确筛选；
- `GET .../monitoring/runs/{run_id}/model-requests`：Run 级 Model Request 分页；
- `GET .../monitoring/runs/{run_id}/command-observations`：按 `after_sequence` 续读 Command 外部观察；
- `GET .../monitoring/runs/{run_id}/state`：latest persisted root State；
- `GET .../monitoring/runs/{run_id}/agent-invocations/{invocation_id}`：exact completed Agent artifact；
- `GET /api/workflow-lifecycles/{lifecycle_id}/download`：下载整个 Lifecycle 的运行监控 ZIP；
- `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download`：下载属于该 Lifecycle 的单个 Run ZIP。

捕获关闭的 Lifecycle 返回 `409 runtime_monitoring_disabled`；不存在的 Lifecycle、Run、Workflow scope、frozen Node 或 invocation 返回对应 404；只提供 `invocation_id` 而未提供 `node_id` 时返回 `422 runtime_monitoring_protocol_selector_invalid`；Registry/snapshot 整体不可读返回 503，归档物化失败返回 `500 runtime_monitoring_archive_failed`。独立资源读取失败返回 `200` 和 `availability=unavailable`，允许其他区域继续显示并在下一轮重试。Protocol/Command 用响应的 `next_after_sequence` 续读；Graph、Run、Node、Model、State 与 Agent artifact 重新读取当前 snapshot/page。

这些 management GET 通过 application database 的异步执行边界读取 SQLite；数据库锁等待不会占用 FastAPI 事件循环。该机制只改变读取工作的执行位置，不把普通 HTTP 轮询升级成推送或强一致实时流。

### 运行数据下载

Lifecycle 与单 Run 使用同一个 `agent-shell.runtime-monitoring-archive.v1` ZIP contract。根目录包含 `manifest.json` 和 `lifecycle.json`；每个纳入范围的 Run 位于独立编号目录，包含 Registry Run、frozen Graph、Node attempt、raw ProtocolEvent、Run 级 Model Request、Command observation、latest persisted State，以及由 exact invocation ID 读取的已完成 Agent artifact 和索引。每个资源保留 `availability`、记录数或读取时间，缺失数据不会被伪装成完整空结果。

活动运行下载在开始时固定 Run 集合以及 Node、Protocol、Model、Command 的当前最大 sequence，之后只读到这些 high-water；下载开始后出现的新 Run 或新记录进入下一次下载。Registry 可变行、State 和 Store artifact 各自保留实际读取时间，因此这是一定会结束的有界持久化快照，不宣称所有文件来自同一数据库时刻。

归档只读取运行监控已经拥有的 canonical facts。Lifecycle input、Run call relation、任意 Store namespace、完整 checkpoint history、日志中心、用户文件、mapped directory 和 Lifecycle 动态目录不进入 ZIP。服务只在 application `runtime/tmp` 创建本次响应的临时目录，响应结束后释放，不建立归档历史或第二份长期运行数据。

### 保留与删除

【系统 / 系统配置】的 `runtime_monitoring_retention_lifecycles` 默认值为 `20`、最小值为 `0`，没有产品最大值。创建 Lifecycle 时以当时的值是否大于 `0` 冻结 `monitoring_capture_enabled`；运行中修改设置不会改变该 Lifecycle 的采集 profile。全局保留数量始终使用最新设置，因此降低数值会立即收敛已经完整终止的数据。

Lifecycle 只有在请求入口 Run 和全部被调用 Run 都进入终态后才取得 `fully_terminal_at`。活动 Lifecycle 不计入保留数量；完整终态的数据按 `(fully_terminal_at, lifecycle_id)` 保留最近 N 个，因此创建较早但结束较晚的长任务按实际结束顺序参与保留。

值为 `0` 时，新 Lifecycle 不写监控事实，但 Registry、Lifecycle input 和 Run call relation 等运行必需控制数据仍服务到完整终态，随后自动清理。自动保留清理删除该 Lifecycle 的 Registry、监控事实、官方 Store input/run-call/invocation/filesystem route，以及应用仍登记的 checkpoint 数据；它不删除日志中心诊断以及任何运行中写入硬盘的用户文件或目录。

单项删除和批量删除同样拒绝 active Lifecycle。Lifecycle 动态模式创建的 `lifecycle-{lifecycle_id}` 目录及其内容属于用户文件，运行监控不登记、保留计数或删除它们；用户通过文件管理入口或宿主文件系统自行管理。批量删除作用于服务端完整匹配集，跳过 active Lifecycle；空搜索条件匹配全部目录记录。

### 敏感内容

启用采集后，frozen Graph、Node/Command metadata、ProtocolEvent、Model Request、Checkpoint State 和 Agent invocation artifact 可以包含 prompt、用户消息、Tool schema/payload、State、路径以及其他运行材料。ProtocolEvent、Model Request 与 State 读取投影的 JSON 转换排除 Secret 类型，并脱敏明确的 credential、API Key、token 和 password 字段；Command 的已校验外部结果与 Agent 的 OpenAI message artifact 保留普通业务内容。平台不能识别用户主动写入普通文本或自定义对象表示中的任意密钥。`agent-shell.env` 是配置 secret 的唯一权威存储，监控 writer 不读取该配置文件。所有读取与下载接口都需要管理鉴权；下载的 ZIP 应按敏感实例数据保管，分享前必须人工检查其中的自由文本、State 和 payload。

## LangSmith

LangSmith 是可选的外部 trace 服务，可查看 prompt、模型输出、工具调用和 LangChain/LangGraph Run/Trace 层级；配置入口见[数据、文件与系统设置](system-management.md)。
应用日志与 trace 是不同的观测面，可通过 request、Lifecycle、Run 或 trace identity 关联，但不互相替代。
