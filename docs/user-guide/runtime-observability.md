# 日志中心与 Graph 运行观测

## 日志中心

【系统 / 日志中心】保存系统事件和结构化运行失败诊断。Graph 运行错误使用通用的 `graph_runtime` component，并通过 subject kind、ID 和名称区分 Main Agent 与 Workflow。诊断条目直接显示 Provider、Tool 或 Graph 的具体异常链、源异常类型以及 request、Lifecycle、Run 和 Thread ID；附件包含本地消费 traceback，跨 Agent Server 的异常还包含 Agent Server source traceback。错误码用于检索和程序分类，不替代异常原因。系统事件的 timestamp、event、category 和 level 保持可解析的结构值；request ID、actor 和 metadata 按实例已保存的 credential 值公开投影。诊断写入自身失败时，服务端 stderr 会输出具体的持久化异常。日志不是已经建立的官方 Run 状态来源。

## 运行监控

【系统 / 运行监控】按 `Lifecycle -> Thread -> Run` 展示本次请求启动的官方 LangGraph 工作。Lifecycle 只是观察、下载和批量操作分组；所有 Run 能力相同，调用关系不会形成 Parent/Child 权限。Studio与Assistant的Graph结构检查不创建Lifecycle记录。

目录列出：

- 涉及的 Main Agent 与 Workflow Graph；
- 创建时间与 Lifecycle 聚合状态；创建时间取 Lifecycle input Store item 与官方 Thread 的最早时间点，Management API 统一返回带 UTC offset 的 ISO timestamp，管理台按浏览器本地时区显示；
- active/total Run 数量；
- error/timeout Run 数量。

入口 Assistant、Thread 或 Run 创建失败时，Lifecycle 直接显示 `error`，并保留 `start_error`、目标 Agent/Workflow 和 request identity。请求入口可以是 Agent 或 Workflow；这个状态只表示官方 Run 建立前的启动失败，因此 Run 数量可以为零。

官方 Run 执行失败时，根 Lifecycle event 显示可读的 `error`、稳定 `error_code` 和可用的 `exception_type`。Agent Server 内部错误 transport 不直接显示为编码文本；无法识别的官方错误字符串保持原文。消息流中的 error event 不会抢先用通用文案覆盖随后到达的根 Lifecycle 失败原因。

任意 Lifecycle 都可以进入监控页。active Lifecycle 不能删除；terminal Lifecycle 可以单项删除或按当前搜索条件批量删除。

## 监控页

左侧按 Thread 列出 Agent 与 Workflow，当前有 pending/running Run 的 Thread 显示动态状态。右侧顶部按创建顺序显示所选 Thread 的 Run；当前真实运行路径通常每个 Thread 只有一个 Run，这一层仍保留 LangGraph 的 Thread/Run 边界。消息或 Graph 视图由当前所选 Thread 的 subject kind 决定，与整个 Lifecycle 最初由 Agent 还是 Workflow 发起无关。

Agent Thread 使用官方 `@langchain/vue useStream` 直接连接已有 `thread_id`：

- 页面进入时从 latest Thread State hydration 已经 checkpoint 的消息；
- Thread 仍 active 时，`useStream.messages` 按官方 message delta 实时增长 reasoning 与 assistant text，Tool、interrupt 和 error 也沿官方 stream 更新；
- State snapshot 提供 hydration 和最终权威 State，不承担 token 流的重建；
- reasoning 与 assistant text 在 Run 结束前使用流式 Markdown 渲染，root Run 结束后同一消息转为 final；Tool 调用与结果在同一条记录中更新；
- Markdown 跟随管理台当前解析后的 light/dark mode；代码块、行内代码、引用、列表等格式使用 `markstream-vue` 自身对应主题变量；
- 页面只观察，不提供输入、停止、approve 或 State 写入操作；离开页面只断开观察，不取消 Run。

Workflow Thread使用只读Vue Flow显示该Lifecycle启动时冻结的原始Workflow画布。Node位置、Control Edge、source/target handle和viewport与当时正式保存的Graph document一致；Node模板、端点和Edge样式与Workflow编辑器共用，以latest Thread State的`next`高亮一个或多个当前节点。active Lifecycle每三秒刷新Lifecycle snapshot、Store和当前Workflow State；终态后保留最终State并停止自动刷新。

右侧数据检查器以可展开字段树显示所选 Thread 的 State 和 Lifecycle namespace 下的 Store item，不把它们转换为第二套字段协议。页面不从 checkpoint history 合成 Agent 信息流，不从事件时间或 namespace 推测 Workflow 执行事实，也不提供 State 修改、Resume、time travel、灾难恢复或自动重新排队。

这些数据以官方`assistant_id`、`thread_id`、`run_id`、Run status和State，以及Lifecycle configuration snapshot中的Workflow document为准。每个Lifecycle在入口Run创建前持久化一次配置：全部已保存Main Agent、全部Component/Subagent、全部enabled Workflow、当前Repository binding/Connection声明和本次运行设置。Python/Skill package、Filesystem、Managed MCP安装与远端服务只保存引用，credential实际值不写入快照。Agent Shell另保存最小Run relation，用于把没有Lifecycle Thread metadata的已登记Run纳入对应Lifecycle。Lifecycle summary将relation/Run metadata投影为统一Graph subject；搜索覆盖Graph kind、配置ID、名称、Lifecycle ID和request ID。

Agent与Workflow Run都使用持久Thread。事件会话结束只关闭观察连接；已经正常提交的历史消息、State、checkpoint和Lifecycle Run relation在服务重启后继续由官方Thread/Store API提供，直到Lifecycle retention或显式删除流程处理该Thread。

## 下载

Lifecycle列表与监控页都可以按需生成监控ZIP。ZIP包含`manifest.json`、Lifecycle snapshot、Lifecycle Store、configuration snapshot、冻结Workflow document、Main Agent Assistant Graph、Thread latest State和完整checkpoint history。manifest记录schema version、导出时间、Lifecycle状态以及每个文件的读取结果。

active Lifecycle 的 Run 和 State 在导出期间可以继续变化，因此 manifest 的 `atomic` 为 `false`。某一 Graph、Thread、State 或 history 已不可用时，manifest 为该项记录局部错误；下载不会读取 LangGraph Dev 内部数据库文件，也不会把缺失数据伪装为空成功。

## 保留与删除

【系统 / 运行监控】顶部的【监控设定】Card 管理 `retained_lifecycles`。默认值为 `20`、最小值为 `0`、没有产品最大值。只计算已结束 Lifecycle；active Lifecycle 不计入保留数量。降低数值后，超出的 terminal Lifecycle 通过公共 Thread/Store 删除 API 清理。

删除Lifecycle会删除其入口与内部启动Run的官方Thread、Run/checkpoint/State，并删除Agent Shell在Server Store中以该Lifecycle为前缀的configuration、input、run relation和filesystem route数据。普通文件、输出媒体和mapped directory是用户产出，不随运行记录删除。

运行错误、诊断附件、监控 ZIP、Lifecycle Store、State、消息和 Tool payload 保留其 owner 提供的业务内容与本机路径；监控数据沿 LangGraph 官方对象读取。错误与 credential 的投影规则见[数据分类与错误披露](../security-and-deployment.md#数据分类与错误披露)。

## API Docs、Studio 与 LangSmith

首页的服务入口 Card 提供当前服务的 API Docs 和 LangGraph Studio 入口。二者使用同一个普通服务端口；API Docs 的 Authorize 和 Studio 连接都填写 management Bearer Token，链接本身不携带 Token。Studio 托管在 `smith.langchain.com`，浏览器必须能访问 Agent Shell 地址。

远程部署应只公开反向代理后的 TLS 地址，并在 `cors_origins` 中明确允许 Studio 或管理前端需要的 origin。浏览器对公网 HTTPS 页面访问 loopback、HTTP 或私网地址可能应用 Private Network Access/混合内容限制；这属于浏览器与部署网络边界，不通过增加 Agent Shell 端口解决。

启用 LangSmith tracing 后，trace payload 由 LangSmith 官方 contract 决定，其中可以包含 prompt、模型输出和工具输入/输出。是否启用由实例所有者决定。
