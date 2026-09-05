# 安全与部署

## 认证

- 除 `/agent-shell/api/health` 外，管理密码保护 `/agent-shell/api/*`；`/admin` 静态应用壳可以匿名加载，但其数据和操作都通过受保护的 management API；
- API Key 保护 `/compat/openai/v1/*`；
- LangGraph Dev 的 Assistant、Thread、Run、State 与 Store 官方路由使用同一个 management Bearer；
- 两者都必须是无空格的可打印 ASCII，均为 write-only；
- `/agent-shell/api/health` 免鉴权用于存活探测，`/agent-shell/api/readiness` 需要 management Bearer 并返回分层就绪状态。

默认监听 `127.0.0.1`，本地模式也始终要求管理密码。管理台、Management API、OpenAI-compatible API 与 LangGraph Dev 官方 API 共用一个普通服务端口；`debug_port` 留空时不创建第二个 listener。监听非 loopback 地址或配置可信代理前，必须在系统配置显式设置 `allow_remote: true` 并配置 API Key。远程部署只需反向代理这个普通服务端口；若显式启用 DAP 调试端口，不应把它作为公共 HTTP 服务发布。生产远程部署应由受信任反向代理提供 TLS、请求体限制、超时与访问控制。

系统配置页提供同一服务端口上的 API Docs 与 LangGraph Studio 入口。`/docs` 和 `/openapi.json` 公开 API schema，便于加载文档和 Authorize UI；Assistant、Thread、Run、Store 与 Management 操作仍要求 management Bearer。链接不携带 credential；API Docs 的 Authorize 与 Studio 的连接配置需要显式填写 management Bearer Token。Studio 页面托管在 `smith.langchain.com`，远程部署需让浏览器可以访问反向代理后的 Agent Shell HTTPS 地址，并在 `cors_origins` 中允许实际使用的 origin。不要公开 DAP listener。

同一 listener 的路径 owner 固定为：`/admin` 属于 Agent Shell 管理台，`/agent-shell/api/*` 属于 Agent Shell API，`/compat/openai/v1/*` 属于 OpenAI-compatible API；`/assistants/*`、`/threads/*`、`/runs/*`、`/store/*`、`/mcp/` 与 `/a2a/{assistant_id}` 保持 LangGraph Agent Server 官方 contract。反向代理不得只转发其中一部分后假设首页、Studio 或 SDK 仍能使用完整服务。

管理台 HTML 使用 `Content-Security-Policy: frame-ancestors 'none'` 拒绝被其他页面嵌入。反向代理不得删除或覆盖这个响应头。

Agent Shell 按单实例、单一所有者信任域设计。管理、审计和日常使用由同一个实例所有者承担；业务 Workflow 和 Run 可以并发执行，运行数据仍归同一个所有者。管理鉴权保护实例入口，不建立多租户数据隔离、SaaS 角色分权或管理者、审计者、用户之间的下载可见性分层。

## CORS 与代理

CORS 只接受明确的 `http://` 或 `https://` origin，不支持 `*`、userinfo、path、query 或 fragment。
可信代理使用精确 CIDR；配置 `trusted_proxy_cidrs` 本身即进入远程模式，未同时设置 `allow_remote: true` 时启动失败。不要信任未受控制的代理网段。

应用只依据当前安全配置解释转发信息。反向代理必须覆盖客户端可伪造的 forwarded headers，并把管理台和推理 API 的访问策略一并纳入部署设计。

## Secret 与用户内容

Provider/MCP credential、API Key、管理密码和 LangSmith API Key 保存在实例 `data/config/` 中：模型连接与 MCP 连接 YAML 只保存 secret 的变量引用，`agent-shell.env` 保存实际敏感值；这些文件不提供加密存储。保护整个 `data/` 的磁盘权限、备份和传输，
不要提交 Git 或公开分享。

应用写入 `agent-shell.env` 时先在同目录创建空临时文件并验证私有权限，再写入内容并原子替换；权限无法确认时保留原文件并让写操作失败。启动时也会复核现存文件权限。该机制只限制本机文件读取主体，不替代磁盘加密和备份保护。

普通 API response、DOM、system log 和 runtime diagnostic summary 不回显 credential、Bearer token、宿主敏感路径、traceback 或 Provider 原始错误正文。以下 management-only 功能会按产品用途保存完整内容：

- 拦截消息页在进程内暂存并展示最新一条 OpenAI 请求原文，服务重启后清空；
- 运行诊断异常自动写入 `data/logs/diagnostics/` 的完整异常详情；
- LangGraph Dev 保存 Assistant、Thread、Run、checkpoint、State/history 与 Server Store 数据；管理 API 通过公共接口读取 Lifecycle 下的官方 Run、Assistant Graph、latest Thread State 和 State history；
- 用户创建的组件、文件和 Python 资源。

运行诊断列表只保存固定结构化身份和安全摘要字段。异常详情附件不经过摘要白名单或脱敏，并只从管理台日志中心对应的运行诊断行下载；它保留 Provider 异常链，供实例维护者调查网关原始响应。正常完成不会产生诊断或附件。

## 配置 Bundle

配置 Bundle 是 management-only 的 ZIP 导入/导出入口，用于迁移单个配置根及其声明式依赖闭包。它不承担实例备份；
不会包含 `system.yaml`、`agent-shell.env`、credential value/environment reference、SQLite、LangGraph Dev 运行数据、日志、媒体、普通文件、
Python template、`skills-template` 公共素材或 runtime cache。模型要求和 MCP 要求会随配置导入；模型/MCP 连接与 credential 需要在目标实例单独维护并完成各自映射。
Skill Component 导出的是该 Component 已拥有的 Skill 独立包。

平台不能可靠识别用户自行写进 prompt、Skill 文件或 Python source 的任意 secret。导出者在分享前仍需审查这些内容；导入者导入未知或不受信任配置是危险操作：Bundle 可能包含以 Agent Shell 权限执行的 Python/Skill 代码、文件系统或网络访问，以及欺骗性引用。导入或分享前必须审查来源、提示词、Skill 文件、Python 源码、requirements、Filesystem binding 与权限；在完成审查前不要启用导入的 Workflow。导入和导出阶段只执行静态语法/manifest/factory contract 扫描，不 import module、不安装 dependency、不调用 factory。

ZIP 接受当前 format version、canonical `manifest.json`、规范相对 POSIX path 和匹配的 SHA-256 asset tree hash；绝对路径、
`..`、反斜杠、重复/大小写冲突 entry、file/directory 前缀冲突、symlink/reparse、未声明文件、未知 kind/type/field 或缺失依赖闭包会被拒绝。Windows 控制字符、不可创建的文件名字符和设备名也在写入 staging 前拒绝。
Bundle 保存 Filesystem 配置引用，宿主文件内容保留在源实例；绝对 mapped path 和全部 virtual source path 在目标实例显式重绑。

导入永不覆盖配置或资产。preview 生成的新 UUID map、bundle digest 与无状态 plan token 必须原样提交；token 同时绑定 active Repository、manifest digest 和 UUID map，名称与 Filesystem binding 仍可填写。Workflow 固定 disabled。提交使用 staging 与 prepared/committed journal，失败或下次启动恢复只清理该 journal 声明的新 UUID 路径，不把导入前对象作为回滚目标。部署侧的反向代理仍负责按实例资源条件设置上传 request body 边界；应用本身不设置 Bundle 大小、文件数或展开字节的硬编码上限。

## 用户代码与文件系统

Custom Tool 和 Custom Middleware 包是受信任的本地代码，真实请求会 import 或执行。只有实例维护者可以管理这些资源，并应预先审查依赖、网络、文件和进程权限。

Windows Middleware 包可以声明公开 PyPI 依赖。uv 优先使用兼容 wheel，没有 wheel 时可以执行发行包的标准源码构建流程；第三方包及其构建后端与包代码具有相同的服务进程权限。
包名仿冒、恶意更新和依赖接管都属于供应链风险。平台固定公开 PyPI、拒绝 requirements 中的 URL/索引配置，
并约束核心版本，但这不代替维护者对包名、发布者、版本和许可证的审查。

Managed Local MCP 软件包同样是受信任的本地代码。管理台只接受 npm/PyPI 包名与精确版本，使用软件内锁定的 Node.js 或 CPython/uv toolchain，在每条 Connection 独立的 `runtime/mcp/` 环境中安装；PyPI 包没有兼容 wheel 时可以执行标准源码构建，并自行使用宿主已有的编译工具。依赖隔离防止其修改核心或 Python 扩展依赖，但不是进程、文件或网络 sandbox。npm 安装脚本与 PyPI 构建后端在安装阶段执行，运行阶段 MCP Server 继承 Agent Shell 服务账号权限以及该 Connection 明确配置的 env/cwd。维护者必须审查包名、发布者、版本、安装脚本、构建后端、许可证和 Server 对外提供的 Tool；不要把版本锁与 SHA/requirements lock 误解为软件包可信证明。

MCP Connection 声明、安装 lock 和 secret 位于 `data/`，可执行软件包、内部 Node toolchain、下载 cache 与运行状态位于可重建的 `runtime/mcp/`。备份或迁移 `data/` 后，需要在目标软件中联网重新安装本地 MCP；Configuration Bundle 不包含 Connection、secret、安装 lock 或依赖。HTTP MCP 不下载本地代码。

Middleware 包没有 sandbox，以 Agent Shell 服务进程权限运行。它可以修改消息、实例文件、持久 Skill、mapped 目录和服务账号可访问的其他宿主资源，也可以发起网络或进程操作。平台不备份、不回滚、不加锁，也不协调多个包的文件或变量冲突。

项目 filesystem 的 mapped directories 可读写宿主真实目录。只映射 Agent 确实需要的路径；写入、编辑和递归删除工具按最小权限启用。Agent 看到的 Skill namespace 始终只读。

LocalShellBackend 的 `execute` 直接以 Agent Shell 服务账号权限在宿主机运行任意命令，没有 sandbox。`virtual_mode=True` 只约束文件工具的路径解析；workspace 只是命令的默认工作目录，不限制命令访问该账号可达的其他文件、进程、网络或系统资源。只在受控开发环境中为可信 Workflow 开启，并使用权限受限的专用服务账号和隔离主机。需要隔离执行时应使用 Deep Agents 官方 sandbox backend；Agent Shell 当前尚未接入该 backend，不能把 LocalShell workspace 当作安全边界。

文件管理页面只接受允许列表内的软件根相对 `data/...` 路径。普通文件、Skill/Python 模板、Python private package 和 Skill package 可编辑；
Component、Agent 与 Workflow 配置树只读。`data/config/`、Repository metadata/import journal、state、logs、media、runtime、
mapped host directory 和软件根目录外路径均不可达。此边界不限制受信任自定义代码或 Agent Filesystem mapping 自身的权限。

## 容量与保留

部署者负责磁盘、内存、上传大小、外部映射和并发限制。Chat 请求体、content block 和输入媒体单项/合计边界可在系统配置中调整，只有正数约束，没有额外产品最大值。Agent 响应媒体落盘和 File Manager 在线文本编辑不设置项目级字节上限；其他文件传输采用流式处理，不构成实例配额。
运行诊断使用可配置保存条数，系统日志使用文件大小上限。运行监控页面的【监控设定】管理 `retained_lifecycles`：按 terminal Lifecycle 数量保留，默认 `20`、最小 `0`、没有产品最大值；active Lifecycle 不计入数量。降低数值会通过公共 Thread/Store 删除 API 清理超出的终态 Lifecycle；`0` 表示不保留已结束 Lifecycle。

Lifecycle retention 和显式删除会删除对应官方 Thread、Run/checkpoint/State，以及 Agent Shell 在 Server Store 中以该 Lifecycle 为前缀的 input、invocation 和 filesystem route 记录。删除日志或运行诊断不会删除这些数据。普通文件、生成媒体、mapped directory 正文和 Lifecycle 动态目录都属于用户产出，不由运行记录清理处理。

官方 Graph、State/history、Server Store 和 Agent invocation artifact 可以包含 prompt、消息、Tool payload、State、路径和其他业务材料。平台不能识别用户主动写入普通文本、异常 message 或自定义对象表示中的任意密钥，实例所有者必须把 `data/state/` 和完整 `data/` 作为敏感数据保护。`/agent-shell/api/workflow-lifecycles/{lifecycle_id}/monitoring/*` 全部需要 management Bearer，不建立新的多租户可见性边界。

## 系统配置与变量

非敏感系统字段位于 `data/config/system.yaml`。以下为与部署直接相关的节选，文件还包含 retention、validation、log 和 runtime policy 等当前系统设置：

```yaml
settings:
  host: 127.0.0.1
  port: 19100
  n_jobs_per_worker: 10
  debug_port: null
  allow_remote: false
  langsmith_tracing_enabled: false
  langsmith_endpoint: https://api.smith.langchain.com
  langsmith_project: agent-shell
  langsmith_workspace_id: null
  cors_origins: []
  trusted_proxy_cidrs: []
api_server:
  enabled: true
  max_initial_messages: 1000
  message_interception_enabled: false
workflow_lifecycles:
  retained_lifecycles: 20
```

`data/config/agent-shell.env` 使用 UTF-8 的标准 dotenv `KEY=value` 格式保存敏感变量，例如：

```dotenv
AGENT_SHELL_MANAGEMENT_TOKEN=<management-token>
AGENT_SHELL_API_KEY=<api-key>
LANGSMITH_API_KEY=<langsmith-api-key>
AGENT_SHELL_MODEL_<UUID_WITHOUT_HYPHENS>_API_KEY=<model-credential>
AGENT_SHELL_MCP_<CONNECTION_UUID_WITHOUT_HYPHENS>_<SLOT_UUID_WITHOUT_HYPHENS>=<mcp-secret>
```

仓库根目录 `.env.example` 只说明这些产品 key 的格式，不参与运行。Model/MCP 的 UUID 部分使用无连字符的大写十六进制；reference 由 Agent Shell 生成和维护，不应手工推导。管理页面按 key 排序写回；普通单行 token 使用裸值，需要保留空白或换行的值使用 dotenv 双引号。读取遵循 `python-dotenv` 的标准行为，包括空行、注释、引用值、`export` 前缀和重复 key 后值生效。文件必须使用 UTF-8 且无 BOM；NUL 或未知的 `AGENT_SHELL_*` key 会使启动失败。

模型连接 YAML 位于 `data/config/model-connections/<uuid>.yaml`，credential 实际值由连接的 env 变量保存；模型要求与模型连接的绑定关系位于 `data/config/model-bindings.yaml`。
模型要求 YAML 只保存名称和说明，写入 Configuration Repository。其他字段（包括 prompt、filesystem、middleware 和 tool 配置）直接写入 YAML。
LangSmith 连接在系统配置中管理；启用或修改 Endpoint、API Key、
Workspace ID 时会在落盘前验证 Key 能否访问对应区域，保存后重启生效。进程使用官方显式 Client 配置，并同步设置 `LANGSMITH_TRACING`、`LANGSMITH_API_KEY`、`LANGSMITH_ENDPOINT`、`LANGSMITH_PROJECT` 和可选 `LANGSMITH_WORKSPACE_ID` 供 LangChain 生态读取。关闭时只在本项目进程环境中强制 tracing 为 `false`。开启后，标准 LangSmith trace 可能上传 prompt、模型输出和工具输入/输出；Agent Shell 不修改 Deep Agents 官方 Middleware trace policy，也不为外部 tracing 恢复上游已省略的 hook input。明确的 credential/API Key/secret 字段继续由项目序列化边界排除或脱敏，但平台不能识别普通文本中自行嵌入的任意密钥，分享或启用外部 tracing 前需要由维护者检查。

实例敏感值只从 `data/config/agent-shell.env` 读取；服务启动和配置 Repository 都不把宿主进程中的同名 Secret 当作回退来源。非敏感 `AGENT_SHELL_*` 启动变量也不作为配置来源；未知键和误放入环境文件的键会使启动失败。Windows 源码启动器读取当前 Clone 的 data 配置；启动和维护方式见[开发与版本](development-and-release.md)。
