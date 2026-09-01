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

【系统 / 运行监控】以一次顶层请求的 Lifecycle 聚合 root Workflow Run 和全部 background Workflow Run，属于需要管理鉴权的实例级功能。当前页面提供可信的 Lifecycle 目录、搜索、分页、单项删除和按当前服务端搜索条件批量删除；目录展示 parent Workflow、创建时间、状态、Run 数量、失败数、Token 用量和本次 Lifecycle 是否启用监控采集。

当前版本只开放持久化目录与删除管理。Lifecycle 详情、事件、single Run 详情和下载接口返回 `503 runtime_monitoring_read_model_unavailable`；页面也不提供 Graph、Node 历史、实时进度或运行归档。监控 read model 完成前，系统不输出缺少事实完整性保证的 Timeline。

### 持久化事实

Runtime Registry 是 Lifecycle 与 Workflow Run 控制事实的权威 owner。每个 root/background Run 使用独立 `run_id`，并保存 parent/background relationship、Workflow identity、状态、起止时间、终止原因、错误码和 usage。Registry 注册、开始或终态提交失败属于运行控制故障，不能作为可选观测写入吞掉。

启用采集的每个 Run 同时保存以下监控事实：

- Run 注册时保存本次实际执行的不可变 `WorkflowGraphDocumentV1`、document SHA、Node source identity 和 Edge class；之后修改或删除 current Workflow 不改变这份 Graph；
- `RunExecution` 在 v3 transformer 之后、应用 direct consumer 已解析 Shell origin 的位置，保存本次实际产生的全部 `ProtocolEvent` envelope 和 origin sidecar。监控不会额外声明 `values`、`updates`、`tasks`、`debug` 等 stream mode，也不会恢复 transformer 已抑制的事件；
- 每次 ChatModel 调用在 LangChain `on_chat_model_start` 边界保存 message batches、绑定 Tool schema、invocation parameters、options、tags 和 metadata，并在 `on_llm_end` 或 `on_llm_error` 保存终态、usage 或安全错误类型。该边界位于 middleware 处理和模型绑定之后、Provider adapter 最终 HTTP 序列化之前；
- Command Node 保存 `started` 与 `completed|failed` 外部观察。成功记录经过校验的 `{activate, dispatch, update}`，失败只记录稳定的 `workflow.command_failed`，不保存脚本源码、locals、MCP session 或完整输入 State。

Graph、ProtocolEvent、Model Request 和 Command 四个分区分别具有 `capturing`、`available`、`partial` 或 `not_applicable` 状态。任一可选 writer 失败只停止该分区后续采集、标记 `partial` 并写一条不含业务正文的运行诊断，不改变 LangGraph 正式结果。进程中断时仍处于采集中的分区标记为 `partial`；Graph 已成功冻结以及本来不适用的分区保持原状态。

Workflow Run 只有在自己的 Workflow 引用 Checkpointer Component 时才拥有 `checkpoint_thread_id`，并由共享的官方 LangGraph `AsyncSqliteSaver` 写入 Checkpoint。Parent 与 background child 独立读取各自冻结配置。Checkpoint 当前只服务 Debug，不提供 Resume、time travel 或灾难恢复入口。

### 保留与删除

【系统 / 系统配置】的 `runtime_monitoring_retention_lifecycles` 默认值为 `20`、最小值为 `0`，没有产品最大值。创建 Lifecycle 时以当时的值是否大于 `0` 冻结 `monitoring_capture_enabled`；运行中修改设置不会改变该 Lifecycle 的采集 profile。全局保留数量始终使用最新设置，因此降低数值会立即收敛已经完整终止的数据。

Lifecycle 只有在 root Run、全部 child Run 和全部 background task 都进入终态后才取得 `fully_terminal_at`。活动 Lifecycle 不计入保留数量；完整终态的数据按 `(fully_terminal_at, lifecycle_id)` 保留最近 N 个，因此创建较早但结束较晚的长任务按实际结束顺序参与保留。服务启动时先把遗留 active Run 和失去进程 owner 的 background task 归一为 `interrupted`，再判断完整终态并执行保留策略。

值为 `0` 时，新 Lifecycle 不写监控事实，但 Registry、Lifecycle input 和 background task 等运行必需控制数据仍服务到完整终态，随后自动清理。自动保留清理删除该 Lifecycle 的 Registry、监控事实、官方 Store input/task/invocation/filesystem route，以及所有非空 `checkpoint_thread_id` 对应的官方 checkpoint；它不删除日志中心诊断、普通用户文件、生成媒体、fixed/mapped directory 正文或 Shell 创建的 Lifecycle 动态目录。

单项删除和批量删除同样拒绝 active Lifecycle。管理台默认保留受管动态目录；management API 只有在显式提交 `delete_dynamic_directories=true` 时才验证并删除目标名为 `lifecycle-{lifecycle_id}` 且直接位于登记 root 下的 Shell-created dynamic directory。批量删除作用于服务端完整匹配集，跳过 active Lifecycle；空搜索条件匹配全部目录记录。

### 敏感内容

启用采集后，ProtocolEvent 和 Model Request 可以包含 prompt、用户消息、Tool schema/payload、State、路径以及其他运行材料。统一 JSON 转换排除 Secret 类型，并脱敏明确的 credential、API Key、token 和 password 字段；平台不能识别用户主动写入普通文本或自定义对象表示中的任意密钥。`agent-shell.env` 仍是配置 secret 的唯一权威存储，监控 writer 不读取该配置文件。当前没有运行归档下载入口；后续分享任何由这些事实生成的归档前仍需人工检查自由文本。

## LangSmith

LangSmith 是可选的外部 trace 服务，可查看 prompt、模型输出、工具调用和 LangChain/LangGraph Run/Trace 层级；配置入口见[数据、文件与系统设置](system-management.md)。
应用日志与 trace 是不同的观测面，可通过 request、Lifecycle、Run 或 trace identity 关联，但不互相替代。
