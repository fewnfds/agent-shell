# 日志中心与 Workflow 观测

## 日志中心

【系统 / 日志中心】只合并两类运维记录：

- 系统日志：服务、配置、安全和管理请求事件；
- 运行诊断：Workflow、Agent、后台任务、持久化或观测链路的失败摘要。

运行诊断使用 `diagnostic_id`，并按可用范围关联 request、Lifecycle、Run、thread、parent Workflow、
当前 subject、Workflow node 和 node invocation。正常完成的 Run 不生成运行诊断。

页面提供时间、来源、级别和全文筛选、摘要查看、按筛选条件批量删除，以及超大 JSON 条目下载。系统日志按文件大小保留，运行诊断按条数保留；两者只清理自己拥有的日志数据。

日志中心不保存 Workflow Lifecycle、Run 历史、Graph State、checkpoint 或 Store 数据，也不负责这些核心运行数据的保留与删除。一次 Lifecycle 的完整输入、多 Run 结构和节点执行历史不能从日志中心还原。

## 异常详情

运行异常产生诊断时，系统同时尝试把完整 Python exception chain 和 traceback 保存到 `data/logs/diagnostics/`，并从对应诊断行下载；正常完成不会产生附件。附件写入失败不会阻塞原运行失败边界，
对应诊断以 `detail_available=false` 表示没有可下载详情。

异常详情可能包含请求内容、Provider 返回、凭据、宿主路径和自定义代码信息。删除诊断或降低诊断保留数时，
对应附件一起删除；附件不具有独立于诊断记录的生命周期。

Provider 有明确 HTTP 状态时，普通 HTTP/SSE 调用方会收到该状态和固定的 `provider_request_failed` 安全说明。原始 Provider 异常仍作为 cause 进入上述完整异常链；实例维护者从日志中心对应的运行诊断行下载附件，才能查看网关返回的真实内容。

## 运行历史

【系统 / 运行历史】以一次顶层请求的 Lifecycle 聚合 root Workflow、background Workflow 和 background Agent Run。
Run Registry 是 Run 身份与终态的权威记录；append-only Event Journal 保存 Run、Workflow Node、Agent、Model 和 Tool 的结构边界。Node 每次执行使用独立 `node_invocation_id/span_id`，同一 Node 的循环、重试和 fan-out 不会合并。
Run 完成、失败、超时或取消时，Journal 会以相同终态关闭仍开放的 Node、Agent、Model 和 Tool span，Timeline 不保留伪 `running` 子项。

每个 Workflow Run 使用独立 thread，并由 LangGraph `AsyncSqliteSaver` 写入 checkpoint；background Agent 明确标记为不具备 checkpoint。Checkpoint 当前只服务 Debug，不提供 Resume。页面可查看 Run 父子关系、结构 Timeline，以及 Checkpoint、结构事件和关联诊断的精确计数；单 Run 详情不展开大量原始条目。需要完整条目时下载单 Run 或整个 Lifecycle 的 management-only 诊断包。

诊断包标注 `captured_at`、当前终态/活动状态、最后事件 sequence 和观测完整性。它不包含 Lifecycle 输入、`messages[]`、
模型正文、Tool/Script payload、Provider 原始响应或 Checkpoint State，也不承诺字节级重放。运行历史没有自动 retention；
只有 Lifecycle 显式删除会清理 Run/Event、Store、Checkpoint 和选择的受管动态目录。

下载时事件按页、checkpoint 按迭代结果写入 `runtime/tmp` 的一次性目录，再生成磁盘 ZIP 并由文件响应发送；响应结束后删除该临时目录。导出不再先把全量记录和 ZIP 同时聚合进进程内存。

## LangSmith

LangSmith 是可选的外部 trace 服务，可查看 prompt、模型输出、工具调用和 LangChain/LangGraph Run/Trace 层级。
应用日志与 trace 是不同的观测面，可通过 request、Lifecycle、Run 或 trace identity 关联，但不互相替代。
