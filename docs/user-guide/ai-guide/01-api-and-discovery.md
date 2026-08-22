# Management API authentication、对象关系与事实发现

配置工作以对象依赖、Management API credential、当前实例 catalog 和已有配置为基础。

## 对象关系

相关对象分为以下几层：

1. **Agent component**：Model Requirement、Agent Event Output、Filesystem、system prompt、Skill、Filesystem Permissions、Custom Middleware 等。
2. **Agent configuration**：Main Agent 引用 component 和 Subagent；Subagent 定义一层同步 delegation 的 target 及 capability override。
3. **Workflow component**：Main Agent 自动成为 Workflow component，其他 component 通常通过 Python package 编程。
4. **Workflow**：保存 execution logic、runtime limits 和一份 Graph document。
5. **Run entry point**：parent Workflow 被直接启用，再通过 Graph 调用其他 Node 或创建 child Run。

## Management API authentication

默认 Management API base URL `http://127.0.0.1:19100`，也可以从配置文件确认。
`/api/*` 使用 management token；`/v1/*` 使用独立的 API Key，两者不能互换。
实例使用自定义 data root 时，`agent-shell.env` 路径来自用户提供的实例信息，无需从源码中搜索。
默认 data root 下的 `data/config/agent-shell.env` 通常包含：

```dotenv
AGENT_SHELL_MANAGEMENT_TOKEN=<token>
```

`key` 是自动化查找配置项的稳定标识。命令可以只引用它，并保存在当前进程变量中，以 PowerShell 为例：

```powershell
$baseUrl = "http://127.0.0.1:19100"
$envFile = Join-Path (Get-Location) "data/config/agent-shell.env"
$tokenLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^AGENT_SHELL_MANAGEMENT_TOKEN=' } |
    Select-Object -First 1
if (-not $tokenLine) { throw "AGENT_SHELL_MANAGEMENT_TOKEN is missing" }
$managementToken = $tokenLine.Substring("AGENT_SHELL_MANAGEMENT_TOKEN=".Length)
$managementHeaders = @{ Authorization = "Bearer $managementToken" }

Invoke-RestMethod "$baseUrl/api/health"
Invoke-RestMethod "$baseUrl/api/readiness" -Headers $managementHeaders
```

## 当前事实入口

以下接口提供配置时需要的当前事实：

| 请求 | 用途 |
| --- | --- |
| `GET /api/catalog` | 当前 component type、required flag、Subagent policy 和 editor defaults |
| `GET /api/workflow-node-catalog` | 当前 Node type/version、`config_schema`、input/output handle 和允许角色 |
| `GET /api/blocks/{type}` | 某类现有 component 及 UUID |
| `GET /api/main-agents`、`GET /api/subagents` | 现有 Agent configuration |
| `GET /api/configuration-repositories` | Configuration Repository 列表与 active Repository；写操作进入 active Repository |
| `GET /api/model-connections` | 当前实例私有模型连接的 masked/missing 投影 |
| `GET /api/model-requirements` | 当前 Configuration Repository 的模型要求及本机绑定投影 |
| `GET /api/workflows?workflow_role=parent` | 现有 parent Workflow |
| `GET /api/skills` | 合法 Skill Template catalog 与不可选择的模板错误 |
| `GET /api/python-package-templates/{kind}` | 当前 script template 和 read-only built-in example |
| `GET /api/validation/repository` | 当前完整 configuration repository 的 validation |
| `POST /api/configuration-bundles/export`、`preview`、`import` | 单根配置 Bundle 导出、预检与提交 |

`{kind}` 当前为 `custom-tool`、`middleware`、`agent-event-output`、`workflow-event-output`、`command` 或 `task-dispatcher`。catalog 是 Node 和 component type 的当前来源；模型连接以 `/api/model-connections` 为事实，模型要求与绑定以 `/api/model-requirements` 为事实。
实例会自动准备默认 Repository；创建或激活其他 Repository 使用 `/api/configuration-repositories` 对应的 POST 入口。管理台【配置库 / 全局 / 组件配置】负责 Repository 操作和单根 Bundle 操作。

写操作通常沿以下数据流进行：

1. 新建 dependency 时由叶到根：component -> Subagent / Main Agent -> Workflow -> Graph -> Run。
2. Workflow 可保存为 `enabled: false` draft；只有 `PUT /api/workflows/{id}/graph` 通过完整 validation 后才设置 `enabled=true`。
3. 保存每次 POST 返回的 UUID；引用永远使用 UUID，不使用显示名称。
4. PUT 是完整可写对象更新，不是 PATCH。普通对象可从 GET 结果移除 `id` 后修改；
    Model Connection PUT 中的 `credential` 接受 `null`（同 Provider/Base URL 时保留旧 Key）或新的 write-only Key，不接受 GET 返回的 masked metadata；
   Python-backed component 的 PUT 只提交 `name` 和原有 `python_package` 引用；源码文件通过 File Manager API 独立修改。
   GET projection 含有 read-only field，因此不能直接原样作为 PUT payload。
5. 422 响应中的 structured issue/path 会指出不符合的 field；删除 field 或降低 constraint 不会替代对应修正。
6. 只要响应含 `X-Request-ID` 或 `request_id`，保留它用于诊断，但不要记录请求中的 secret 或用户隐私。

下一步：[配置 Agent](02-components-and-agents.md)。
