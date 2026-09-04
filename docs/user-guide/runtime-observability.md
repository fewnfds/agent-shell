# 日志中心与 Workflow 观测

## 日志中心

【系统 / 日志中心】保存系统事件和结构化运行失败诊断。诊断条目可以包含 request、Lifecycle、Run 和 Thread ID，详细 traceback 只对持有管理 Bearer Token 的用户开放。日志不是 Run 状态来源，也不会复制用户消息或 Provider 原始响应。

## 运行监控

【系统 / 运行监控】按 Lifecycle 展示本次请求启动的所有官方 LangGraph Run。Lifecycle 只是观察和批量操作分组；所有 Run 能力相同，调用关系不会形成 Parent/Child 权限。

目录列出：

- 涉及的 Workflow 名称；
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

这些数据以官方 `assistant_id`、`thread_id`、`run_id` 和 status 为准。页面不重建第二套 Registry，不从 event 时间或 namespace 推测执行事实，也不提供 State 修改、Resume、time travel、灾难恢复或自动重新排队。

## 保留与删除

【系统 / 系统配置】的 `retained_lifecycles` 默认 `20`、最小 `0`、没有产品最大值。只计算已结束 Lifecycle；active Lifecycle 不计入保留数量。降低数值后，超出的 terminal Lifecycle 通过公共 Thread/Store 删除 API 清理。

删除 Lifecycle 会删除其官方 Thread、Run/checkpoint/State 和 Agent Shell 在 Server Store 中以该 Lifecycle 为前缀的数据。普通文件、输出媒体和 mapped directory 是用户产出，不随运行记录删除。

## API Docs、Studio 与 LangSmith

系统配置页提供当前服务的 API Docs 和 LangGraph Studio 入口。二者使用同一个普通服务端口；API Docs 的 Authorize 和 Studio 连接都填写 management Bearer Token，链接本身不携带 Token。Studio 托管在 `smith.langchain.com`，浏览器必须能访问 Agent Shell 地址。

远程部署应只公开反向代理后的 TLS 地址，并在 `cors_origins` 中明确允许 Studio 或管理前端需要的 origin。浏览器对公网 HTTPS 页面访问 loopback、HTTP 或私网地址可能应用 Private Network Access/混合内容限制；这属于浏览器与部署网络边界，不通过增加 Agent Shell 端口解决。

启用 LangSmith tracing 后，官方 trace 可能上传 prompt、模型输出和工具输入/输出。启用前应按敏感数据策略检查项目与工作区。
