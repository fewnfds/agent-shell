# 数据、文件与系统设置

## 实例数据

`data/` 是完整实例数据根：

```text
data/
  config/
    active-configuration-repository.json
    system.yaml
    agent-shell.env
    model-connections/<uuid>.yaml
    model-bindings.yaml
  config_repos/<repository-name>/
    repository.json
    components/ agents/ workflows/
    python_packages/ skill_packages/
    configuration_imports/
      journals/<transaction-uuid>.json
      staging/<transaction-uuid>/
  state/agent-shell.sqlite3*
  state/langgraph-dev/.langgraph_api/   LangGraph Dev 的 Assistant、Thread、Run、State 与 Store 数据
  files/
    generated/<YYYY-MM>/<request-id>/  Agent 响应生成的媒体文件
  skills-template/
  templates/
    agent/custom_tool/
    agent/custom_middleware/
    agent/agent_event_output/
    workflow/command/
    workflow/workflow_event_output/
  logs/security-events.jsonl
  logs/diagnostics/*.log
```

它包含管理密码、API Key、Provider/MCP credential、Workflow、Agent/组件配置、用户文件、最终响应媒体和运行数据，应作为敏感数据整体备份。可装配配置文件位于 `data/config_repos/`；`data/config/` 保存系统配置、secret env、active pointer、实例模型/MCP 连接与映射。`agent-shell.sqlite3` 只保存结构化 runtime 失败诊断。LangGraph Dev 把 Assistant、Thread、Run、checkpoint、State/history、Server Store、Lifecycle input、Filesystem route 和Graph Run调用关系集中写入 `data/state/langgraph-dev/.langgraph_api/`；这是官方运行时拥有的内部目录，Agent Shell 只通过公开 SDK/API 读写，不解析其中的文件。迁移时先完全停止服务，再复制完整 `data/`，包括当时存在的 SQLite、WAL、SHM 和 `.langgraph_api` 数据。外部 filesystem 映射需要单独迁移并更新路径。

静态 Python 模板保存在 `data/templates/`，配置独占的 Python 扩展及其可选 `requirements.txt` 保存在 `data/config_repos/<repository-name>/python_packages/`。两者都属于需备份的 data；Windows 生成的共享依赖位于 `runtime/python_packages/site-packages/` 及 dependency state，属于可重建 runtime，不进入备份。模板不运行且不参与依赖。

模型连接是实例私有资源：Provider、endpoint、具体 model 和请求参数保存在 `data/config/model-connections/<uuid>.yaml`，credential value 保存在 `data/config/agent-shell.env`。
`data/config/model-bindings.yaml` 按 Configuration Repository 保存模型要求到模型连接的映射。模型连接和映射都不进入配置 Bundle。
MCP 连接保存在 `data/config/mcp-connections/<uuid>.yaml`，secret env/Header 的值保存在 `data/config/agent-shell.env`；`data/config/mcp-bindings.yaml` 按 Configuration Repository 保存 MCP 要求到 MCP 连接的映射。MCP 连接、映射和 secret 都不进入配置 Bundle。
切换 Configuration Repository 只改变可装配配置和当前使用的 repository-scoped binding；上述系统设置、secret、SQLite 数据、普通文件、模板和 Model/MCP Connection 保持不变。

## 文件管理

顶层【文件管理】使用相对软件根目录的真实路径，从 `data/` 开始显示允许访问的目录。页面支持浏览、新建、
上传、下载、ZIP、重命名、UTF-8 文本编辑和递归删除。

可见目录包括普通文件 `data/files/`、Skill 模板 `data/skills-template/`、Python 模板 `data/templates/`，以及每个 Configuration Repository 中的 Component、Agent、Workflow、Python private package 与 Skill package。Agent 响应中的受支持 Base64 图片、音频、视频和文件会保存到 `data/files/generated/<YYYY-MM>/<request-id>/`；客户端收到包含具体文件路径的文字，文件可在这里下载、改名或删除，不随服务重启自动清理。`components/`、`agents/`、`workflows/` 可以查看和下载，内容修改仍通过对应配置页面完成。两类 package 支持文件操作。Python package 的结构和 factory contract 会在组件检查或运行装配时校验；Skill 独立包的问题只在 Skill 组件页载入或显式刷新时显示 warning，不阻塞保存、Repository 切换或 Bundle 操作。

- 路径和面包屑直接显示 `data/...` 的真实目录名；
- 在线文本编辑只接受UTF-8普通文件，不设置项目级字节上限；
- 文件打开时记录内容 revision。磁盘内容发生变化后，保存会保留页面草稿并提供重新载入、确认覆盖或继续编辑；
- 编辑期间不锁定磁盘文件，外部编辑器和文件管理页面都可以修改同一文件；
- 文件操作不跟随符号链接或 Windows reparse point（含 `data/` 根与每段路径的检查）；
- `data/config/`、Repository metadata/import journal、`data/state/`、`data/logs/`、`runtime/`、外部映射和其他宿主路径不开放；
- 系统设置、env secret、模型连接/映射和 MCP 连接/映射只通过对应页面管理；
- 递归删除没有回收站。

`data/templates/` 用于按 `agent/custom_tool/`、`agent/custom_middleware/`、`agent/agent_event_output/`、
`workflow/command/` 和 `workflow/workflow_event_output/` 五个类别维护静态 Python 模板。
创建 Python-backed Component 时选择一份合法模板；保存后形成配置独占的完整文件目录（目录名等于 Component 配置名称，`package.json.id` 等于 Component UUID）。

## 配置管理

【配置库 / 全局 / 组件配置】列出全部 Configuration Repository 和 active 状态，提供切换、复制、下载和删除。当前 active Repository 的删除按钮不可用，后端也会拒绝该请求。复制会生成全新的 Repository 与配置 UUID，重写全部声明式引用，复制 Python private package、Skill package 和 repository-scoped Model/MCP Mapping，并把 Workflow 固定为 disabled；Model/MCP Connection 和 secret 仍由实例拥有，不进入副本或下载。详见[管理配置库](configuration-library.md)。

【配置库 / 全局 / 模型连接】直接复用模型连接的通用列表，只提供查看、编辑、复制和删除，不提供下载。编辑页位于【模型 / 模型连接】；模型映射边界见[模型](models.md)。

【配置库 / 全局 / MCP 连接】直接复用 MCP 连接的通用列表，只提供查看、编辑、复制和删除，不提供下载或筛选后批量删除。编辑与 JSON 导入位于【MCP / MCP 连接】，Repository binding 位于【MCP / MCP 映射】；完整边界见 [MCP 连接、映射与调用](mcp.md)。

## 系统设置

【系统 / 系统配置】页面从上到下展示 Agent Shell API Server、代理设置、限制策略、响应流调度、LangGraph Dev、LangSmith 和配置校验。代理设置、限制策略、响应流调度、LangGraph Dev 与 LangSmith 使用 `PUT /agent-shell/api/system/settings`；Agent Shell API Server 使用 `PUT /agent-shell/api/api-server`；配置校验使用 `PUT /agent-shell/api/validation/settings`。每张 Card 有自己的 Save、校验和错误反馈；保存一个区域只采用该区域的草稿，其他区域的未保存修改不会一起提交。页面管理监听地址、普通服务端口、可选 DAP 调试端口、LangGraph 官方运行限制、远程访问、管理密码、API Key、LangSmith tracing、Endpoint、Project、可选 Workspace ID 与 write-only API Key，以及 CORS origins 和可信代理 CIDR。API Docs 与 LangGraph Studio 位于首页的服务入口 Card，链接不携带 Token。secret 只显示是否配置，不回显明文。

LangGraph Dev 与管理台、Management API 和 OpenAI-compatible API 运行在同一个进程，并共用 `host` 与普通 `port`。`debug_port` 默认留空；填写 `1..65535` 且不同于普通端口的值后才会额外启动 DAP listener。

限制策略包含三个官方运行字段：`n_jobs_per_worker` 默认 `20`，控制单 worker 同时处理的 Run 槽位；`recursion_limit` 默认 `100000`，达到后由 LangGraph 抛出 `GraphRecursionError`；`max_concurrency` 默认 `20`，控制 Graph 内并行任务，留空时不向 `RunnableConfig` 传值。三者只接受正整数且没有产品最大值，增大会提高 CPU、内存和外部请求压力。它们与其他系统启动设置在服务重启后生效。

响应流调度直接保存全局`response_stream_scheduling`：`idle_timeout_seconds`默认`10`，控制当前writer全静默多久后让位；`max_batch_kb`默认`64`，控制一次公开发送的软批次大小；`send_interval_seconds`默认`0.05`，控制连续批次的最小间隔。前两项必须大于零，发送间隔可以为零。保存立即生效于后续Lifecycle，已经开始的Lifecycle继续使用请求创建时冻结的副本。调度单位是官方Graph的`(thread_id, run_id)`；Run终态立即让位，静默超时只切换writer，不取消Run。

Agent Shell API Server 区域只设置 API Key。OpenAI-compatible 请求不设置 Agent Shell 项目级请求体、消息条数、content block 数量或解码媒体字节上限。模型请求 timeout 由 Model Connection 的 Provider 官方字段或 Provider SDK 默认行为负责；模型目录读取复用共享 Provider HTTP client，Agent Shell 不额外设置 timeout。生成媒体落盘和 File Manager 在线文本编辑同样不设置项目级字节上限，实际能力由 Provider、内存、磁盘和操作系统决定。

【系统 / 运行监控】顶部的【监控设定】Card 管理 `retained_lifecycles`。默认值为 `20`、最小值为 `0`，没有产品最大值；只计算 terminal Lifecycle，active Lifecycle 不计入数量。`0` 表示不保留已结束的 Lifecycle；降低数值会通过公共 Thread/Store 删除 API 清理超出的终态运行数据。普通文件、生成媒体和 mapped directory 不随 Lifecycle 自动清理。已由关联 Middleware 登记的 Async Subagent child 属于父 Lifecycle 的运行记录与 retention 范围。完整边界见[日志中心与 Workflow 观测](runtime-observability.md)。

Agent Shell API Server、代理设置、限制策略、响应流调度、LangGraph Dev 和 LangSmith 分别使用自己的 Card 和 Save。代理设置包含监听地址、普通端口、远程访问、管理密码、CORS 与可信代理；Agent Shell API Server 只管理 API Key，Lifecycle 保留数量由运行监控页面的监控设定单独保存。

当前锁定版本的 LangGraph Dev 公共 CLI 没有关闭 API Docs 或 Studio 的配置选项。API Docs 路由由官方开发服务提供，Studio 链接指向 LangSmith 托管页面；首页服务入口 Card 提供入口，不把它们伪装成可关闭的本地开关。需要对外隐藏这些路径时，应在反向代理层按部署策略阻断，而不是修改 Agent Shell 的官方 API contract。


LangSmith 配置项含义如下：

- 启用 LangSmith：控制是否向 LangSmith 发送 trace；
- 服务地址：LangSmith API Endpoint，按账号区域或自托管部署填写；
- 项目：接收 trace 的 LangSmith Project；
- Workspace ID：API Key 可访问多个 Workspace 时填写，否则留空；
- API Key：只写 secret；已配置的值不会回显，留空保存时保留原值。

当开启 LangSmith 且 Endpoint、API Key 或 Workspace ID 发生变化时，保存前会校验连通性；关闭 tracing 时不校验。API Key、配置校验去抖和响应流调度立即生效；最新 Lifecycle 保留数量会立即收敛已结束数据。host、普通端口、Run 槽位数、Graph运行限制、DAP 调试端口、远程访问、管理密码、LangSmith、CORS 和可信代理重启后生效。拦截消息开关见下节，同样立即生效。

【系统 / 拦截消息】管理 Chat Completions 入站拦截。开关立即生效并持久化；开启后，请求会在进入root Graph前直接收到 OpenAI-compatible 的“消息已拦截”回复。页面只暂存进程内最新一条原始 JSON，正文不写入 SQLite、
系统日志或运行诊断；开关从关闭变为开启或服务重启时清空，关闭期间不捕获。已开启时重复保存不会清空当前原文。日志中心另见[日志中心与 Workflow 观测](runtime-observability.md)。
远程部署要求见[安全与部署](../security-and-deployment.md)。

【系统 / 日志中心】展示系统日志和运行失败诊断，不承载 Lifecycle、Run、checkpoint 或 Store 数据。运行诊断按可用范围关联 request、Lifecycle、Run、Workflow 和当前 subject。正常完成不生成诊断。新异常的完整 exception chain 和 traceback 自动写入 `data/logs/diagnostics/`，写入成功时可从对应诊断行下载；日志中心不提供采集开关。
