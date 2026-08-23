# 日志中心与 Workflow 观测

## 日志中心

【系统 / 日志中心】只合并两类运维记录（management-only，需要管理鉴权；相关系统设置见[数据、文件与系统设置](system-management.md)）：

- 系统日志：服务、配置、安全和管理请求事件；
- 运行诊断：Workflow、Agent、后台任务、持久化或观测链路的失败摘要。

运行诊断使用 `diagnostic_id`，并按可用范围关联 `request_id`、`lifecycle_id`、`run_id`、`thread_id`、parent Workflow、
`subject_kind/id/name`、Workflow node、`node_invocation_id` 和 `exception_type`；没有值的字段不存储。正常完成的 Run 不生成运行诊断。

页面提供时间、来源、级别和全文筛选、摘要查看、按筛选条件批量删除，以及超大 JSON 条目下载。系统日志按文件大小保留（默认 `5 MiB`，最小 `1 MiB`），运行诊断按条数保留（默认 `20` 条，最小 `1` 条）；两者只清理自己拥有的日志数据。

日志中心不保存 Workflow Lifecycle、Run 历史、Graph State、checkpoint 或 Store 数据，也不负责这些核心运行数据的保留与删除。一次 Lifecycle 的完整输入、多 Run 结构和节点执行历史不能从日志中心还原。

## 异常详情

运行异常产生诊断时，系统同时尝试把完整 Python exception chain 和 traceback 保存到 `data/logs/diagnostics/diagnostic-{diagnostic_id}.log`，并从对应诊断行下载；正常完成不会产生附件。诊断包内归档名为 `diagnostics/{diagnostic_id}.log`。附件写入失败不会阻塞原运行失败边界，
对应诊断以 `detail_available=false` 表示没有可下载详情。

异常详情可能包含请求内容、Provider 返回、凭据、宿主路径和自定义代码信息；普通 API、DOM、系统日志和诊断摘要仍按脱敏边界不回显这些内容，只有 management-only 的异常详情附件可由维护者下载查看。删除诊断或降低诊断保留数时，
对应附件一起删除；附件不具有独立于诊断记录的生命周期。

Provider 有明确 4xx/5xx 状态时，普通 HTTP 调用方收到该状态和固定的 `provider_request_failed` 安全说明；SSE 已建立为 200 时则在最终 `chat.completion.chunk` 中返回 `finish_reason="error"` 和 `error.code="provider_request_failed"`，随后发送 `[DONE]`。原始 Provider 异常仍作为 cause 进入上述完整异常链；实例维护者从日志中心对应的运行诊断行下载附件，才能查看网关返回的真实内容。

## 运行历史

【系统 / 运行历史】以一次顶层请求的 Lifecycle 聚合 root Workflow、background Workflow 和 background Agent Run（management-only，需要管理鉴权；导出接口见[使用 background Run](ai-guide/05-background-runs.md)）。
Run Registry 是 Run 身份与终态的权威记录；append-only Event Journal 保存 Run、Workflow Node、Agent、Model 和 Tool 的结构边界。Workflow Node 每次执行使用独立 `span_id`，其 `node_invocation_id` 与该 `span_id` 相同；Agent、Model 和 Tool 拥有自己的 `span_id/parent_span_id`，并保留所属 `node_invocation_id`。同一 Node 的循环、重试和 fan-out 不会合并。
Run 完成、失败、超时或取消时，Journal 会以相同终态关闭仍开放的 Node、Agent、Model 和 Tool span，Timeline 不保留伪 `running` 子项。

只有 `run_kind=workflow` 的 Run 使用独立 thread，并由 LangGraph `AsyncSqliteSaver` 写入 checkpoint；`run_kind=agent`（当前为 background Agent）标记为 `checkpoint_available=false`，不装配独立 checkpointer。Checkpoint 当前只服务 Debug，不提供 Resume。页面可查看 Run 父子关系、结构 Timeline，以及 Checkpoint 摘要、结构事件和关联诊断的计数；页面不直接展开 Checkpoint State 和运行消息。

每次 LangChain ChatModel 调用开始时，Run Journal 通过 `on_chat_model_start` 持久化该调用看到的完整 message batches、已绑定 Tool schemas、`tool_choice`、模型 invocation parameters、options、tags 和 metadata。记录使用 model callback run ID 幂等写入，并关联 Lifecycle/Run、Workflow Node、Main Agent profile；Subagent 记录同时关联自己的 profile 和父 Main Agent profile。记录失败只把 Run observation 标为 `partial` 并生成运行诊断，不中断模型调用。

运行历史直接提供 Lifecycle ZIP 和单 Run ZIP。ZIP 标注 `captured_at`、当前终态/活动状态、最后事件 sequence 和观测完整性，并固定包含下载时可读取的 Run Registry、结构事件、Lifecycle 输入、持久化 Agent invocation artifact、上述 ChatModel 请求、后台任务记录、完整 Checkpoint State、Lifecycle Store 摘要与原始记录、诊断摘要和现存异常详情附件。模型请求索引位于 `model-requests/index.json`；Main Agent 分别写入 `model-requests/main-agents/*.jsonl`，Subagent 按父 Main Agent scope 写入 `model-requests/subagents/<parent-scope>/*.jsonl`，没有混合所有 Agent 的聚合请求文件。

运行详情 ZIP 是持久化运行快照，不承诺字节级重放。`on_chat_model_start` 位于 LangChain ChatModel 边界，可以稳定观察 middleware 处理后的消息和绑定到模型调用的 Tool/参数，但它不是 Provider adapter 最终序列化出的 HTTP payload；Provider 网络请求原文和成功 Provider HTTP 原始响应不持久化。下载没有敏感度分类或内容开关；写入运行记录的 prompt、用户消息、Tool schema/payload、State、路径和其他敏感材料会进入 ZIP。配置 secret 的实际值由 `agent-shell.env` 单独持有，运行历史下载不读取该配置文件；请求序列化也会排除 Secret 类型和明确的 credential 字段。运行历史没有自动 retention；只有 Lifecycle 显式删除会清理 Run/Event、Model Request、Store、Checkpoint 和选择的受管动态目录。

下载时事件按页、checkpoint 按迭代结果写入实例 `runtime/tmp` 下的一次性目录，再生成磁盘 ZIP 并由文件响应发送；响应结束后删除该临时目录。导出过程使用磁盘流式组装。

## LangSmith

LangSmith 是可选的外部 trace 服务，可查看 prompt、模型输出、工具调用和 LangChain/LangGraph Run/Trace 层级；配置入口见[数据、文件与系统设置](system-management.md)。
应用日志与 trace 是不同的观测面，可通过 request、Lifecycle、Run 或 trace identity 关联，但不互相替代。
