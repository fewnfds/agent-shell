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
  state/workflow-checkpoints.sqlite3*   首次运行启用 Checkpointer 的 Workflow 时建立
  state/workflow-store.sqlite3*
  files/
  media/outputs/                 最终响应媒体私有资产（不在文件管理中开放）
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

它包含管理密码、API Key、Provider credential、Workflow、Agent/组件配置、用户文件、最终响应媒体和历史，应作为敏感数据整体备份。可装配配置文件位于 `data/config_repos/`；`data/config/` 保存系统配置、secret env、active pointer、实例模型连接和模型映射。`agent-shell.sqlite3` 保存 Lifecycle Run Registry/Event Journal、结构化 runtime 失败诊断和媒体元数据，`workflow-checkpoints.sqlite3` 只保存已启用检查点保存器的 Workflow Run 的官方 LangGraph Debug checkpoint，并在首次实际使用时建立；`workflow-store.sqlite3` 保存 Lifecycle 和 Workflow Store 数据。迁移时先完全停止服务，再复制完整 `data/`，包括当时实际存在的 SQLite、WAL 和 SHM 文件。外部 filesystem 映射需要单独迁移并更新路径。

静态 Python 模板保存在 `data/templates/`，配置独占的 Python 扩展及其可选 `requirements.txt` 保存在 `data/config_repos/<repository-name>/python_packages/`。两者都属于需备份的 data；Windows 生成的共享依赖位于 `runtime/python_packages/site-packages/` 及 dependency state，属于可重建 runtime，不进入备份。模板不运行且不参与依赖。

模型连接是实例私有资源：Provider、endpoint、具体 model 和请求参数保存在 `data/config/model-connections/<uuid>.yaml`，credential value 保存在 `data/config/agent-shell.env`。
`data/config/model-bindings.yaml` 按 Configuration Repository 保存模型要求到模型连接的映射。模型连接和映射都不进入配置 Bundle。
切换 Configuration Repository 只改变可装配配置和当前使用的 repository-scoped binding；上述系统设置、secret、SQLite 数据、普通文件、模板和模型连接保持不变。

## 文件管理

顶层【文件管理】使用相对软件根目录的真实路径，从 `data/` 开始显示允许访问的目录。页面支持浏览、新建、
上传、下载、ZIP、重命名、UTF-8 文本编辑和递归删除。

可见目录包括普通文件 `data/files/`、Skill 模板 `data/skills-template/`、Python 模板 `data/templates/`，以及每个 Configuration Repository 中的 Component、Agent、Workflow、Python private package 与 Skill package。`components/`、`agents/`、`workflows/` 可以查看和下载，内容修改仍通过对应配置页面完成。两类 package 支持文件操作。Python package 的结构和 factory contract 会在组件检查或运行装配时校验；Skill 独立包的问题只在 Skill 组件页载入或显式刷新时显示 warning，不阻塞保存、Repository 切换或 Bundle 操作。

- 路径和面包屑直接显示 `data/...` 的真实目录名；
- 文本编辑默认上限为 2 MiB，可在【系统 / 系统配置】调整；
- 文件打开时记录内容 revision。磁盘内容发生变化后，保存会保留页面草稿并提供重新载入、确认覆盖或继续编辑；
- 编辑期间不锁定磁盘文件，外部编辑器和文件管理页面都可以修改同一文件；
- 文件操作不跟随符号链接或 Windows reparse point（含 `data/` 根与每段路径的检查）；
- `data/config/`、Repository metadata/import journal、`data/state/`、`data/logs/`、`data/media/`、`runtime/`、外部映射和其他宿主路径不开放；
- 系统设置、env secret、模型连接和模型映射只通过对应页面管理；
- 递归删除没有回收站。

`data/templates/` 用于按 `agent/custom_tool/`、`agent/custom_middleware/`、`agent/agent_event_output/`、
`workflow/command/` 和 `workflow/workflow_event_output/` 五个类别维护静态 Python 模板。
创建 Python-backed Component 时选择一份合法模板；保存后形成配置独占的完整文件目录（目录名等于 Component 配置名称，`package.json.id` 等于 Component UUID）。

## 配置管理

【配置库 / 全局 / 组件配置】列出全部 Configuration Repository 和 active 状态，提供切换、复制、下载和删除。当前 active Repository 的删除按钮不可用，后端也会拒绝该请求。复制会生成全新的 Repository 与配置 UUID，重写全部声明式引用，复制 Python private package、Skill package 和 repository-scoped 模型映射，并把 Workflow 固定为 disabled；模型连接和 credential 仍由实例拥有，不进入副本或下载。详见[管理配置库](configuration-library.md)。

【配置库 / 全局 / 模型连接】直接复用模型连接的通用列表，只提供查看、编辑、复制和删除，不提供下载。编辑页位于【模型 / 模型连接】；模型映射边界见[模型](models.md)。

## 系统设置

【系统 / 系统配置】页面聚合展示三类后端设置：系统网络、LangSmith 与代理设置（`PUT /api/system/settings`）；API Server 的 API Key 与 `max_initial_messages`（`PUT /api/api-server`）；Workflow Debug 采集、9 项限制策略与配置校验去抖（`PUT /api/system/runtime-policy` 与 `PUT /api/validation/settings`）。页面管理监听地址、端口、远程访问、管理密码、API Key、初始消息条数上限、LangSmith tracing、Endpoint、Project、可选 Workspace ID 与 write-only API Key，以及 CORS origins 和可信代理 CIDR。secret 只显示是否配置，不回显明文。

“请求与限制策略”集中设置 `workflow_debug_capture_enabled`（默认关闭）、`max_initial_messages`（默认 `1000`）、配置校验去抖（默认 `1000 ms`，最小值由后端返回）、Chat 请求体、content block 数量、单个/合计输入媒体、单个输出媒体、在线编辑文件以及 Provider 总超时、连接超时和模型目录超时。后端通过 `/api/system/runtime-policy` 返回 Debug 开关和 9 项数值 runtime-policy 的当前值与默认值，以及数值策略的最小值；`max_initial_messages` 与去抖分别由 API Server 和 `/api/validation/settings` 返回。
9 项 runtime-policy 只有正数约束，没有额外产品最大值；默认值依次为：Chat 请求体 `64 MiB`、content block `4096`、单个输入媒体 `24 MiB`、合计输入媒体 `48 MiB`、单个输出媒体 `64 MiB`、在线编辑文件 `2 MiB`、Provider 总超时 `600 秒`、连接超时 `5 秒`、模型目录超时 `15 秒`。

Workflow Debug 采集在新 Run 创建执行对象时冻结设置值。开启后，Run Event Journal 不再对白名单外的 LangChain callback metadata 做字段过滤，而是保存经过 JSON 转换且 credential 字段脱敏的完整 metadata；每次 Chain、Model 和 Tool callback failure 都额外生成一条运行诊断及完整 exception chain/traceback 附件，包括被 Retry Middleware 恢复的中间失败。该模式显著增加 SQLite 运行历史和 `data/logs/diagnostics/` 的写入量，关闭后恢复轻量结构事件；切换不会改变已经启动的 Run。

系统配置页面按网络、请求与限制策略（含 Debug 采集、消息上限、校验去抖与 9 项数值 runtime-policy）、LangSmith 和代理设置分卡展示；管理密码与 API Key 均归入网络卡片，Debug 开关和消息上限位于请求与限制策略卡片。

限制策略中的容量字段以 MiB 展示（1 MiB = 1024² bytes），保存时仍按后端要求换算为 bytes。

LangSmith 配置项含义如下：

- 启用：控制是否向 LangSmith 发送 trace；
- 服务地址：LangSmith API Endpoint，按账号区域或自托管部署填写；
- 项目：接收 trace 的 LangSmith Project；
- Workspace ID：API Key 可访问多个 Workspace 时填写，否则留空；
- API Key：只写 secret；已配置的值不会回显，留空保存时保留原值。

当开启 LangSmith 且 Endpoint、API Key 或 Workspace ID 发生变化时，保存前会校验连通性；关闭 tracing 时不校验。API Key、消息上限、校验去抖和限制策略立即生效，Debug 开关从下一个新 Run 起生效；host、端口、远程访问、管理密码、LangSmith、CORS 和可信代理重启后生效。拦截消息开关见下节，同样立即生效。

【系统 / 拦截消息】管理 Chat Completions 入站拦截。开关立即生效并持久化；开启后，请求会在进入 Workflow 前直接收到 OpenAI-compatible 的“消息已拦截”回复。页面只暂存进程内最新一条原始 JSON，正文不写入 SQLite、
系统日志或运行诊断；开关从关闭变为开启或服务重启时清空，关闭期间不捕获。已开启时重复保存不会清空当前原文。日志中心另见[日志中心与 Workflow 观测](runtime-observability.md)。
远程部署要求见[安全与部署](../security-and-deployment.md)。

【系统 / 日志中心】展示系统日志和运行失败诊断，不承载 Lifecycle、Run、checkpoint 或 Store 数据。运行诊断按可用范围关联 request、Lifecycle、Run、parent Workflow 和当前 subject。正常完成不生成诊断。新异常的完整 exception chain 和 traceback 自动写入 `data/logs/diagnostics/`，写入成功时可从对应诊断行下载；日志中心不提供采集开关。
