# 日志中心与 Graph 运行观测

## 日志中心

【系统 / 日志中心】保存系统事件和结构化运行失败诊断。Graph 运行错误使用通用的 `graph_runtime` component，并通过 subject kind、ID 和名称区分 Main Agent 与 Workflow。诊断条目可以包含 request、Lifecycle、Run 和 Thread ID，详细 traceback 只对持有管理 Bearer Token 的用户开放。日志不是 Run 状态来源，也不会复制用户消息或 Provider 原始响应。

## 运行监控

【系统 / 运行监控】按 Lifecycle 展示本次请求启动的所有官方 LangGraph Run。Lifecycle 只是观察和批量操作分组；所有 Run 能力相同，调用关系不会形成 Parent/Child 权限。官方 Async Subagent 创建的后台 child 也作为普通 Run 进入同一目录；它使用独立 Thread，父 Agent 仍通过 `async_tasks`和五个 task Tool 管理任务。

目录列出：

- 涉及的 Main Agent 与 Workflow Graph；
- 创建时间与 Lifecycle 聚合状态；
- active/total Run 数量；
- error/timeout Run 数量。

任意 Lifecycle 都可以进入监控页。active Lifecycle 不能删除；terminal Lifecycle 可以单项删除或按当前搜索条件批量删除。

## Run 详情

监控页直接组合 LangGraph Dev 公共 API：

- snapshot：Lifecycle 下的 Thread 和 Run；
- Graph：该 Run 使用的 Assistant Graph；
- State：Thread 的 latest persisted State；
- history：Thread 的 checkpoint/State history。

这些数据以官方 `assistant_id`、`thread_id`、`run_id` 和 status 为准。Async child 的官方 Thread 初始没有 Shell Lifecycle metadata，目录使用工具边界保存的最小 Run relation 将其纳入同一查询和删除范围；relation 不复制 child State、正文或 status。页面不重建第二套 Registry，不从 event 时间或 namespace 推测执行事实，也不提供 State 修改、Resume、time travel、灾难恢复或自动重新排队。

Lifecycle summary 将每个 Run 的 metadata 投影为统一 Graph subject；搜索覆盖 Graph kind、配置 ID 和名称。Run 选择列表按 `graph_kind` 显示 `main_agent_name` 或 `workflow_name`，身份 metadata 缺失时显示 `run_id`。

## 保留与删除

【系统 / 运行监控】顶部的【监控设定】Card 管理 `retained_lifecycles`。默认值为 `20`、最小值为 `0`、没有产品最大值。只计算已结束 Lifecycle；active Lifecycle 不计入保留数量。降低数值后，超出的 terminal Lifecycle 通过公共 Thread/Store 删除 API 清理。

删除 Lifecycle 会删除其入口与内部启动 Run 的官方 Thread、Run/checkpoint/State，包括已登记的 Async Subagent child，并删除 Agent Shell 在 Server Store 中以该 Lifecycle 为前缀的数据。普通文件、输出媒体和 mapped directory 是用户产出，不随运行记录删除。

## API Docs、Studio 与 LangSmith

首页的服务入口 Card 提供当前服务的 API Docs 和 LangGraph Studio 入口。二者使用同一个普通服务端口；API Docs 的 Authorize 和 Studio 连接都填写 management Bearer Token，链接本身不携带 Token。Studio 托管在 `smith.langchain.com`，浏览器必须能访问 Agent Shell 地址。

远程部署应只公开反向代理后的 TLS 地址，并在 `cors_origins` 中明确允许 Studio 或管理前端需要的 origin。浏览器对公网 HTTPS 页面访问 loopback、HTTP 或私网地址可能应用 Private Network Access/混合内容限制；这属于浏览器与部署网络边界，不通过增加 Agent Shell 端口解决。

启用 LangSmith tracing 后，官方 trace 可能上传 prompt、模型输出和工具输入/输出。启用前应按敏感数据策略检查项目与工作区。
