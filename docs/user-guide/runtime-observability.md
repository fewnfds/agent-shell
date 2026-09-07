# 日志中心与 Graph 运行观测

## 日志中心

【系统 / 日志中心】保存系统事件和结构化运行失败诊断。Graph 运行错误使用通用的 `graph_runtime` component，并通过 subject kind、ID 和名称区分 Main Agent 与 Workflow。诊断条目直接显示 Provider、Tool 或 Graph 的具体异常链、源异常类型以及 request、Lifecycle、Run 和 Thread ID；附件包含本地消费 traceback，跨 Agent Server 的异常还包含 Agent Server source traceback。错误码用于检索和程序分类，不替代异常原因。诊断写入自身失败时，服务端 stderr 会输出具体的持久化异常。日志不是已经建立的官方 Run 状态来源。

## 运行监控

【系统 / 运行监控】按 `Lifecycle -> Thread -> Run` 展示本次请求启动的官方 LangGraph 工作。Lifecycle 只是观察、下载和批量操作分组；所有 Run 能力相同，调用关系不会形成 Parent/Child 权限。

目录列出：

- 涉及的 Main Agent 与 Workflow Graph；
- 创建时间与 Lifecycle 聚合状态；
- active/total Run 数量；
- error/timeout Run 数量。

入口 Assistant、Thread 或 Run 创建失败时，Lifecycle 直接显示 `error`，并保留 `start_error`、目标 Main Agent/Workflow 和 request identity。这个状态只表示官方 Run 建立前的启动失败，因此 Run 数量可以为零。

官方 Run 执行失败时，根 Lifecycle event 显示可读的 `error`、稳定 `error_code` 和可用的 `exception_type`。Agent Server 内部错误 transport 不直接显示为编码文本；无法识别的官方错误字符串保持原文。消息流中的 error event 不会抢先用通用文案覆盖随后到达的根 Lifecycle 失败原因。

任意 Lifecycle 都可以进入监控页。active Lifecycle 不能删除；terminal Lifecycle 可以单项删除或按当前搜索条件批量删除。

## 监控页

左侧按 Thread 列出 Main Agent 与 Workflow，当前有 pending/running Run 的 Thread 显示动态状态。右侧顶部按创建顺序显示所选 Thread 的 Run；当前真实运行路径通常每个 Thread 只有一个 Run，这一层仍保留 LangGraph 的 Thread/Run 边界。

Main Agent Thread 使用官方 `@langchain/vue useStream` 直接连接已有 `thread_id`：

- 页面进入时先从 latest Thread State 恢复已经 checkpoint 的消息；
- Thread 仍 active 时，`useStream` 加入官方 Thread stream，继续更新当前 reasoning、assistant text、Tool、interrupt 和 error；
- reasoning 与 assistant text 使用流式 Markdown 渲染；Tool 调用与结果在同一条记录中更新；
- 页面只观察，不提供输入、停止、approve 或 State 写入操作；离开页面只断开观察，不取消 Run。

Workflow Thread 使用只读 Vue Flow 显示 Assistant Graph，以 latest Thread State 的 `next` 高亮一个或多个当前节点。active Lifecycle 每三秒刷新 Lifecycle snapshot、Store 和当前 Workflow State；终态后保留最终 State 并停止自动刷新。

右侧数据检查器以可展开字段树显示所选 Thread 的 State 和 Lifecycle namespace 下的 Store item，不把它们转换为第二套字段协议。页面不从 checkpoint history 合成 Agent 信息流，不从事件时间或 namespace 推测 Workflow 执行事实，也不提供 State 修改、Resume、time travel、灾难恢复或自动重新排队。

这些数据以官方 `assistant_id`、`thread_id`、`run_id`、Run status、Graph 和 State 为准。Agent Shell 只保存最小 Run relation，用于把没有 Lifecycle Thread metadata 的已登记 Run 纳入对应 Lifecycle。Lifecycle summary 将 relation/Run metadata 投影为统一 Graph subject；搜索覆盖 Graph kind、配置 ID、名称、Lifecycle ID 和 request ID。

`checkpoint_mode=disabled` 的 Main Agent 使用官方 Stateless Run。运行期间创建的临时 Thread 可被监控；事件会话结束后临时 Thread 被删除，Lifecycle relation 继续存在，因此该 Run 的历史消息、State 和 checkpoint 显示为 unavailable。Workflow 始终使用持久 Thread，没有 Stateless 模式。

## 下载

Lifecycle 列表与监控页都可以按需生成监控 ZIP。ZIP 包含 `manifest.json`、Lifecycle snapshot、Lifecycle Store、去重后的 Assistant Graph、Thread latest State 和完整 checkpoint history。manifest 记录 schema version、导出时间、Lifecycle 状态以及每个文件的读取结果。

active Lifecycle 的 Run 和 State 在导出期间可以继续变化，因此 manifest 的 `atomic` 为 `false`。某一 Graph、Thread、State 或 history 已不可用时，manifest 为该项记录局部错误；下载不会读取 LangGraph Dev 内部数据库文件，也不会把缺失数据伪装为空成功。

## 保留与删除

【系统 / 运行监控】顶部的【监控设定】Card 管理 `retained_lifecycles`。默认值为 `20`、最小值为 `0`、没有产品最大值。只计算已结束 Lifecycle；active Lifecycle 不计入保留数量。降低数值后，超出的 terminal Lifecycle 通过公共 Thread/Store 删除 API 清理。

删除 Lifecycle 会删除其入口与内部启动 Run 的官方 Thread、Run/checkpoint/State，并删除 Agent Shell 在 Server Store 中以该 Lifecycle 为前缀的数据。普通文件、输出媒体和 mapped directory 是用户产出，不随运行记录删除。

运行错误、诊断附件、监控 ZIP、Lifecycle Store、State、消息和 Tool payload 都可能包含完整业务内容、本机路径或异常中出现的 credential。下载文件离开实例保留边界后由下载者负责保存和删除。

## API Docs、Studio 与 LangSmith

首页的服务入口 Card 提供当前服务的 API Docs 和 LangGraph Studio 入口。二者使用同一个普通服务端口；API Docs 的 Authorize 和 Studio 连接都填写 management Bearer Token，链接本身不携带 Token。Studio 托管在 `smith.langchain.com`，浏览器必须能访问 Agent Shell 地址。

远程部署应只公开反向代理后的 TLS 地址，并在 `cors_origins` 中明确允许 Studio 或管理前端需要的 origin。浏览器对公网 HTTPS 页面访问 loopback、HTTP 或私网地址可能应用 Private Network Access/混合内容限制；这属于浏览器与部署网络边界，不通过增加 Agent Shell 端口解决。

启用 LangSmith tracing 后，官方 trace 可能上传 prompt、模型输出和工具输入/输出。启用前应按敏感数据策略检查项目与工作区。
