# Management API、对象关系与事实发现

本章的目标是在写入任何配置前，确认当前实例的访问方式、active Configuration Repository、可用类型、现有对象和真实 UUID。完成本章后，AI 应持有一份可继续创建对象的 reference ledger。

## 1. 确认 base URL 与两类 credential

默认 Management API base URL 是 `http://127.0.0.1:19100`，实际地址以用户提供的运行实例为准。

Agent Shell 使用两个 credential domain：

| API | credential | 用途 |
| --- | --- | --- |
| `/api/*` | management token | 读取和修改配置、validation、启动 API Server、查看 Lifecycle |
| `/v1/*` | API Key | 列出 enabled parent Workflow、发起真实 Workflow invocation |

`GET /api/health` 是匿名存活探测。其他 `/api/*` 请求通常使用 `Authorization: Bearer <management-token>`；`/v1/*` 使用 `Authorization: Bearer <api-key>`。两类 credential 不能互换。

实例使用自定义 data root 时，`agent-shell.env` 路径来自用户提供的实例信息。默认 data root 下的 `data/config/agent-shell.env` 通常包含：

```dotenv
AGENT_SHELL_MANAGEMENT_TOKEN=<token>
```

下面是 PowerShell 读取默认配置并完成第一次探测的示例：

```powershell
$baseUrl = "http://127.0.0.1:19100"
$envFile = Join-Path $PWD.Path "data/config/agent-shell.env"
$tokenLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -match '^AGENT_SHELL_MANAGEMENT_TOKEN=' } |
    Select-Object -First 1
if (-not $tokenLine) { throw "AGENT_SHELL_MANAGEMENT_TOKEN is missing" }
$managementToken = $tokenLine.Substring("AGENT_SHELL_MANAGEMENT_TOKEN=".Length)
if ($managementToken.StartsWith('"') -and $managementToken.EndsWith('"')) {
    $managementToken = ConvertFrom-Json -InputObject $managementToken
}
$managementHeaders = @{ Authorization = "Bearer $managementToken" }

Invoke-RestMethod "$baseUrl/api/health"
Invoke-RestMethod "$baseUrl/api/readiness" -Headers $managementHeaders
```

AI 不应把 token、API Key、Provider credential 写入 Workflow State、Graph document、日志、诊断说明或最终交付报告。

## 2. 零基础 discovery 顺序

按以下顺序读取事实，再决定是否创建对象：

1. 调用 `GET /api/health`，确认 HTTP service 可访问；
2. 调用 `GET /api/readiness`，确认 Management API 已准备好；
3. 调用 `GET /api/configuration-repositories`，记录 active Repository；
4. 调用 `GET /api/catalog`，读取 component type、required flag、Subagent policy 和 editor defaults；
5. 调用 `GET /api/workflow-node-catalog`，读取 Node type/version、`config_schema` 和 handle；
6. 调用 `GET /api/configuration-options`，一次取得当前 Repository 的引用摘要；需要检查完整配置或复用现有对象时，再直接读取对应完整 collection 或单项 Get；
7. 需要 Python-backed component 时，读取对应 template catalog；
8. 需要 Agent Node 时，读取 Model Requirement、Model Connection 和 binding 状态；
9. 调用 `GET /api/validation/repository`，了解写入前已经存在的 error 或 warning；
10. 建立 reference ledger，再开始 POST/PUT。

不要根据记忆猜测 catalog key、template revision、UUID、Node handle 或 active Repository。每个实例的当前 response 是配置输入。

## 3. 当前事实入口

| 请求 | 用途 |
| --- | --- |
| `GET /api/catalog` | current Component type、required flag、Subagent policy 和 editor defaults |
| `GET /api/workflow-node-catalog` | current Node type/version、`config_schema`、input/output handle 和允许角色 |
| `GET /api/configuration-options` | active Repository identity/revision，以及全部 Component、Agent、Workflow 引用摘要 |
| `GET /api/blocks/{type}` | 某类现有 component 的完整 collection；`/{id}` 读取一条完整记录 |
| `GET /api/main-agents`、`GET /api/subagents` | 完整 Agent configuration collection；`/{id}` 读取一条完整记录 |
| `GET /api/configuration-repositories` | Repository 列表和 active Repository；配置写入 active Repository |
| `GET /api/model-connections` | 当前实例私有 Model Connection 的 masked/missing projection |
| `GET /api/model-requirements` | current Configuration Repository 的 Model Requirement 及本机 binding projection |
| `GET /api/workflows?workflow_role=parent` | 现有 parent Workflow 完整 collection；`/{id}` 读取一条完整 metadata |
| `GET /api/skills` | 可选择的 Skill Template catalog 及模板错误 |
| `GET /api/python-package-templates/{kind}` | 当前 script template 和 read-only built-in example |
| `GET /api/validation/repository` | 当前完整 Configuration Repository validation |
| `POST /api/configuration-bundles/export`、`preview`、`import` | 单根 Configuration Bundle 导出、预检和提交 |

`{kind}` 当前为 `custom-tool`、`middleware`、`agent-event-output`、`workflow-event-output`、`command` 或 `task-dispatcher`。Node 和 component type 以 catalog 为准；Model Connection 以 `/api/model-connections` 为准；Model Requirement 与 binding 以 `/api/model-requirements` 为准。

### Collection representation

管理台与 AI 使用同一套 `/api/*`。Component、Main Agent、Subagent 和 Workflow collection 有两种读取方式：

- 省略 `view/q/offset/limit`：返回完整对象数组，适合 AI 在一次请求中取得一类配置的完整 authoring context；不会隐式分页或截断；
- `view` 决定 item projection：省略或使用 `view=full` 时 item 保持完整读取 projection，`view=summary` 时 item 只保留列表/引用字段；只要显式提交 `view/q/offset/limit`，response 就使用 `items`、`total`、`repository_id`、`repository_revision` envelope；
- `GET /collection/{id}`：读取一条完整配置，适合编辑、复核或 Debug 单个对象；
- `GET /api/configuration-options`：一次取得引用 ledger 所需的摘要，不包含 prompt、Graph、Python/Skill package 等大字段。

AI 不需要为了获得完整 collection 逐条 Get。只需要 UUID 和引用候选时优先使用 `configuration-options`；需要检查全部 payload 时直接使用默认完整 collection；只处理一个对象时使用单项 Get。`repository_revision` 是当前进程内的内容一致性身份，不是发布版本或历史号。

`q` 对 Component/Main Agent 搜索 name 和 UUID，对 Subagent 搜索 component name、task route、description 和 UUID，对 Workflow 搜索 name、description 和 UUID；Workflow 继续用 `workflow_role` 限定 parent/child。批量删除可以提交明确的 `ids`，或提交与列表相同的 `q` predicate；两者只能选一个，Workflow query delete 同时提交对应 `workflow_role`。

软件实例会自动准备 default Configuration Repository。创建或激活其他 Configuration Repository 使用 `/api/configuration-repositories` 的对应 POST endpoint。管理台【配置库 / 全局 / 组件配置】提供 Repository 操作和 single-root Bundle 操作。

## 4. 建立 reference ledger

AI 应在自己的工作记忆中维护一张简短 ledger。它用于后续 payload 组装，不写入产品 State：

```json
{
  "active_repository_id": "<repository UUID>",
  "components": {
    "model_requirement": "<UUID>",
    "agent_event_output": "<UUID>",
    "command": "<UUID>",
    "checkpointer": "<UUID-or-null>"
  },
  "agents": {
    "main": "<UUID>"
  },
  "workflow": {
    "id": "<UUID>",
    "name": "ai-workflow"
  },
  "model_binding": {
    "requirement_id": "<UUID>",
    "connection_id": "<UUID-or-null>"
  }
}
```

每次 POST 成功后立即记录 response 中的 UUID。Configuration reference 使用 UUID；显示名称只用于人类识别。Graph 的 Node ID 和 Edge ID 是 Workflow-local key，不加入全局 component reference。

## 5. 对象依赖与写入方向

依赖对象按叶到根创建：

```text
component -> Subagent / Main Agent -> Workflow -> Graph -> Run
```

一个常见的 Agent Workflow 写入顺序是：

1. 创建 Model Requirement 和 Agent Event Output；
2. 按需创建 System Prompt、AAP、Tool、Skill、Filesystem 等 optional component；
3. 按需创建 Subagent；
4. 创建 Main Agent，并引用 component/Subagent UUID；
5. 需要 Debug 检查点时创建 Checkpointer Component；
6. 创建 parent Workflow，并用可空 `checkpointer_id` 明确选择【无】或已有 Checkpointer；
7. 创建 Graph document，并引用 Main Agent、Command 或 Task Dispatcher UUID；
8. 保存 draft、validate、publish；
9. 完成 Model Mapping；
10. 通过 `/v1` 发起真实 invocation。

确定性 Graph 没有 Agent Node 时，可以直接从 Command/Task Dispatcher component 和 Workflow 开始。

## 6. GET projection 与 PUT payload

GET response 是读取 projection，可能包含 `id`、状态、masked credential、计算字段和其他 read-only field。Collection summary envelope 不是 PUT payload；完整 collection 与单项 Get 中的每条记录也仍是读取 projection。PUT 接收该对象的完整可写 payload，不要把 GET response 原样提交给 PUT。

修改对象时按以下步骤处理：

1. GET 当前对象；
2. 根据对应 endpoint contract 选择可写字段；
3. 保留未修改的必需可写字段；
4. 修改目标字段；
5. 移除 `id`、状态、masked metadata 和其他 read-only field；
6. PUT 完整可写对象；
7. 再次 GET，确认持久化结果。

普通对象通常可以从 GET projection 移除 `id` 和只读字段后修改。以下对象需要特别处理：

- Model Connection PUT 中的 `credential` 接受 `null`，在 Provider 和 Base URL 相同时保留旧 Key；也可以提交新的 write-only Key；GET 返回的 masked metadata 不能作为 credential 回写；
- Python-backed component 的 PUT 只提交 `name` 和原有 `python_package` reference；源码文件通过 File Manager API 独立修改；
- Checkpointer Component 的可写字段是 `name` 和 `durability=exit|async|sync`，默认 `async`；Workflow metadata 使用可空 `checkpointer_id` 引用它，默认 `null`；
- Workflow Graph 使用专用 draft、validate 和 publish endpoint，不通过 Workflow metadata PUT 替代。

Graph 的三步写入语义是：

```text
PUT  /api/workflows/{id}/draft
POST /api/workflows/{id}/validate
PUT  /api/workflows/{id}/graph
```

`/draft` 保存 wire-valid candidate 并设置 `enabled=false`；`/validate` 只读预检；`/graph` 在完整 validation 通过后保存并设置 `enabled=true`。

## 7. 错误处理

先读取 HTTP status、response body、structured error code、`detail`、`issues[]`、`path`、`owner_id` 和 `request_id`。一次只修复 response 指向的 owner 和 field，然后重试原操作。

| 状态 | 优先检查 |
| --- | --- |
| `401` / `403` | API domain、credential、Authorization header 和访问范围 |
| `404` | base URL、endpoint、active Repository、目标 UUID 是否存在 |
| `409` | 名称/identity 冲突、对象仍被引用、operation conflict 或当前状态不允许该操作 |
| `422` | JSON shape、required field、catalog identity、Graph wire、引用、package 或 Agent assembly |
| `5xx` | service log、Provider/外部服务、dependency、运行资源和返回的 request ID |

Graph validation 返回多个 issue 时，修正全部 `severity=error`；warning 可以保留，但应理解其运行影响。保留 response 中的 `X-Request-ID` 或 `request_id` 便于诊断，不复制请求 secret 或用户隐私。

## 8. 进入下一章前的检查

满足以下条件后再创建 Agent 或 Graph：

- base URL 和 management token 已确认可用；
- health 与 readiness 成功；
- active Configuration Repository 已记录；
- `/api/catalog` 与 `/api/workflow-node-catalog` 已读取；
- `/api/configuration-options` 已读取，目标类型需要复用或 Debug 时也已读取对应完整对象；
- 需要的 template `key` 和 `revision` 来自当前 catalog；
- reference ledger 已建立；
- 已知当前 repository validation 中哪些问题属于本次工作；
- 需要 Agent Node 时，用户已建立 Model Connection，或该用户操作已明确列为待办。

下一步：Graph 含 Agent Node 时阅读[配置 Agent](02-components-and-agents.md)；确定性 Graph 可以直接阅读[创建 Workflow Graph](03-workflow-graph.md)。
