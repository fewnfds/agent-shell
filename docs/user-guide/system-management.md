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
  configuration-repositories/<repository-uuid>/
    repository.json
    components/ agents/ workflows/
    python_package_instances/ skill_package_instances/
    configuration-imports/
  state/agent-shell.sqlite3*
  files/
  skills-template/
  templates/
    agent/{custom_tool,custom_middleware,agent_event_output}/
    workflow/{command,task_dispatcher,workflow_event_output}/
  logs/security-events.jsonl
  logs/diagnostics/*.log
```

它包含管理密码、API Key、Provider credential、Workflow、Agent/组件配置、用户文件和历史，应作为敏感数据
整体备份。可装配配置文件位于 `data/configuration-repositories/`；`data/config/` 保存系统配置、secret env、active pointer、实例模型连接和模型映射。SQLite 保存官方 LangGraph checkpoint、Lifecycle Run Registry/Event Journal、
结构化 runtime 失败诊断和媒体元数据。迁移时先完全停止服务，
再复制完整 `data/`，包括 SQLite WAL/SHM。外部 filesystem 映射需要单独迁移并更新路径。

静态 Python 模板保存在 `data/templates/`，配置独占的 Python 扩展及其可选 `requirements.txt` 保存在
`data/configuration-repositories/<repository-uuid>/python_package_instances/`。两者都属于需备份的 data；Windows 生成的共享依赖位于
`runtime/python_packages/`，属于可重建运行态，不进入备份。模板不运行且不参与依赖。

模型连接是实例私有资源：Provider、endpoint、具体 model 和请求参数保存在
`data/config/model-connections/<uuid>.yaml`，credential value 保存在 `data/config/agent-shell.env`。
`data/config/model-bindings.yaml` 按 Configuration Repository 保存模型要求到本机连接的映射。模型连接和映射都不进入配置 Bundle。
切换 Configuration Repository 只改变可装配配置和当前使用的 repository-scoped binding；上述系统设置、secret、SQLite 数据、普通文件、模板和模型连接保持不变。

## 文件管理

顶层【文件管理】使用相对软件根目录的真实路径，从 `data/` 开始显示允许访问的目录。页面支持浏览、新建、
上传、下载、ZIP、重命名、UTF-8 文本编辑和递归删除。

可见目录包括普通文件 `data/files/`、Skill 模板 `data/skills-template/`、Python 模板 `data/templates/`，以及每个
Configuration Repository 中的 Component、Agent、Workflow 和配置私有包。`components/`、`agents/`、`workflows/`
可以查看和下载，内容修改仍通过对应配置页面完成。Python 与 Skill 私有包支持文件操作。Python 私有包的结构和 factory contract 会在组件检查或运行装配时校验；Skill 私有包的问题只在 Skill 组件页载入或显式刷新时显示 warning，不阻塞保存、装配、Repository 切换或 Bundle 操作。

- 路径和面包屑直接显示 `data/...` 的真实目录名；
- 文本编辑默认上限为 2 MiB，可在【系统 / 系统配置】调整；
- 文件打开时记录内容 revision。磁盘内容发生变化后，保存会保留页面草稿并提供重新载入、确认覆盖或继续编辑；
- 编辑期间不锁定磁盘文件，外部编辑器和文件管理页面都可以修改同一文件；
- 文件操作不跟随符号链接或 Windows reparse point；
- `data/config/`、Repository metadata/import journal、`data/state/`、`data/logs/`、`data/media/`、外部映射和其他宿主路径不开放；
- 系统设置、env secret、模型连接和模型映射只通过对应页面管理；
- 递归删除没有回收站。

`data/templates/` 用于按 `agent/custom_tool/`、`agent/custom_middleware/`、`agent/agent_event_output/`、
`workflow/command/`、`workflow/task_dispatcher/` 和 `workflow/workflow_event_output/` 六个类别维护静态 Python 模板。
创建 Python-backed Component 时选择一份合法模板；保存后形成配置独占的完整文件目录。

## 系统设置

【系统 / 系统配置】管理监听地址、端口、远程访问、管理密码、API Key、初始消息条数上限、
LangSmith tracing、Endpoint、Project、可选 Workspace ID 与 write-only API Key，以及 CORS origins 和可信代理
CIDR。secret 只显示是否配置，不回显明文。启用 LangSmith 或修改连接字段时，系统会在保存前验证 API Key、
Endpoint 区域和 Workspace ID 是否匹配；验证失败时不保存本次修改。

“输入与资源策略”集中设置 Chat 请求体、content block 数量、单个/合计输入媒体、单个输出媒体、在线编辑文件以及
Provider 总超时、连接超时和模型目录超时。后端通过 `/api/system/runtime-policy` 返回当前值、默认值和最小值；
这些字段只有正数约束，没有额外产品最大值。当前默认分别为 64 MiB、4096、24 MiB、48 MiB、64 MiB、2 MiB、
600 秒、5 秒和 15 秒。

LangSmith 配置项含义如下：

- 启用：控制是否向 LangSmith 发送 trace；
- 服务地址：LangSmith API Endpoint，按账号区域或自托管部署填写；
- 项目：接收 trace 的 LangSmith Project；
- Workspace ID：API Key 可访问多个 Workspace 时填写，否则留空；
- API Key：只写 secret；已配置的值不会回显，留空保存时保留原值。

API Key、消息上限和输入与资源策略立即生效；host、端口、远程访问、管理密码、LangSmith、CORS 和可信代理重启后生效。

【系统 / 拦截消息】管理 Chat Completions 入站拦截。开关立即生效并持久化；开启后，请求会在进入 Workflow 前
直接收到 OpenAI-compatible 的“消息已拦截”回复。页面只展示进程内最新一条原始 JSON，正文不写入 SQLite、
系统日志或运行诊断，服务重启后清空。
远程部署要求见[安全与部署](../security-and-deployment.md)。

【系统 / 日志中心】展示系统日志和运行失败诊断，不承载 Lifecycle、Run、checkpoint 或 Store 数据。运行诊断按可用范围
关联 request、Lifecycle、Run、parent Workflow 和当前 subject。正常完成不生成诊断。新异常的完整 exception chain
和 traceback 自动写入 `data/logs/diagnostics/`，写入成功时可从对应诊断行下载；日志中心不提供采集开关。
