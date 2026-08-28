# 发现当前实例事实

本章适用于所有配置任务。在创建或修改任何对象前完成本章。

完成结果是一份当前实例的 reference ledger，以及继续设计 Workflow 所需的 Catalog、现有对象和配置状态。

## 1. 确认地址和 credential domain

默认 Management API base URL 是 `http://127.0.0.1:19100`。实际地址以用户提供的运行实例为准。

Agent Shell 使用两类 credential：

- `/api/*` 使用 management token，负责配置、validation、API Server 控制和 Lifecycle 管理；
- `/v1/*` 使用独立 API Key，负责列出和运行 enabled parent Workflow。

`GET /api/health` 是匿名存活探测。其他 `/api/*` 请求通常需要：

```http
Authorization: Bearer ${AGENT_SHELL_MANAGEMENT_TOKEN}
```

`/v1/*` 请求需要：

```http
Authorization: Bearer ${AGENT_SHELL_API_KEY}
```

`${...}` 在本指南中表示 HTTP client 从 AI 进程环境注入值，不是要按字面发送的 header 内容。两类 credential 不能互换：`AGENT_SHELL_MANAGEMENT_TOKEN` 只用于 `/api/*`，`AGENT_SHELL_API_KEY` 只用于 `/v1/*`。

AI 只确认所需环境变量是 present 还是 missing，并在发出请求时直接引用它。不应打印、回显、转存或在命令参数中展开 secret；不应直接读取实例的 `agent-shell.env`；不应要求用户在对话、任务材料或交付报告中粘贴明文。登录失败时，应向用户报告，由用户配置后再继续。

先调用：

```text
GET /api/health
GET /api/readiness
```

health 失败时先解决地址或服务问题。readiness 失败时读取 structured response，不继续写配置。

## 2. 按顺序读取事实

依次调用：

1. `GET /api/configuration-repositories`，记录 active Repository；
2. `GET /api/catalog`，读取 Component type、required flag、Subagent policy 和 editor default；
3. `GET /api/workflow-node-catalog`，读取 Node type、version、`config_schema`、input handle、output handle 和允许的 Workflow role；
4. `GET /api/configuration-options`，取得当前 Repository 的引用摘要；
5. 读取准备复用、修改或排查的完整对象；
6. 需要 Python-backed component 时，读取对应 template catalog；
7. 需要 Agent Node 时，读取 Model Requirement、Model Connection 和 binding 状态；
8. `GET /api/validation/repository`，记录写入前已有的 error 和 warning。

不要根据模型记忆猜测 Catalog key、template revision、UUID、Node handle 或 active Repository。

## 3. 常用事实入口

- `GET /api/catalog` 返回当前 Component contract；
- `GET /api/workflow-node-catalog` 返回当前 Node 和 endpoint contract；
- `GET /api/configuration-options` 返回 active Repository identity、revision 和可引用对象摘要；
- `GET /api/blocks/{type}` 返回某类 Component；`GET /api/blocks/{type}/{id}` 返回一条完整记录；
- `GET /api/main-agents` 和 `GET /api/subagents` 返回 Agent configuration；
- `GET /api/workflows?workflow_role=parent` 返回 parent Workflow；role 可以改为 `child`；
- `GET /api/model-connections` 返回当前实例私有 Model Connection 的 masked 或 missing projection；
- `GET /api/model-requirements` 返回当前 Repository 的 Model Requirement 和本机 binding projection；
- `GET /api/skills` 返回可选择的 Skill Template；
- `GET /api/python-package-templates/{kind}` 返回 Python template catalog；
- `GET /api/validation/repository` 返回当前 Repository validation report。

当前 Python template kind 包括 `custom-tool`、`middleware`、`agent-event-output`、`workflow-event-output`、`command` 和 `task-dispatcher`。仍应以当前实例 endpoint response 为准。

Model Connection 不属于 Configuration Repository，也不进入 Configuration Bundle。Model Requirement、Component、Agent 和 Workflow 属于 active Repository。

## 4. 正确读取 collection

Component、Main Agent、Subagent 和 Workflow collection 支持两种表示：

- 不提交 `view`、`q`、`offset`、`limit` 时，response 是完整对象数组，不会隐式分页；
- 只要显式提交上述任一 collection 参数，response 就使用 `items`、`total`、`repository_id`、`repository_revision` envelope。

`view=full` 返回完整 item projection，`view=summary` 返回引用和列表所需字段。只需要 UUID 和候选引用时，优先读取 `/api/configuration-options`。只修改一个对象时，优先读取单项 GET。

`repository_revision` 表示当前进程内的 Repository 内容一致性身份，不是发布版本或历史版本。

## 5. 建立 reference ledger

在 AI 当前工作记忆中维护简短 ledger。它不写入 Workflow State。

```json
{
  "active_repository_id": "<repository UUID>",
  "components": {
    "model_requirement": null,
    "agent_event_output": null,
    "command": null,
    "task_dispatcher": null,
    "checkpointer": null,
    "workflow_event_output": null,
    "response_stream_scheduling": null
  },
  "agents": {
    "main": null,
    "subagents": []
  },
  "workflow": {
    "id": null,
    "name": null,
    "role": "parent"
  },
  "model_binding": {
    "requirement_id": null,
    "connection_id": null
  }
}
```

每次 POST 成功后立即保存 response 中的 UUID。显示名称只用于识别，不代替 reference。

Graph Node ID 和 Edge ID 是 Workflow-local identity，不加入全局 Configuration reference。

对象通常按依赖从叶到根创建：

```text
Component
  -> Subagent
  -> Main Agent
  -> Workflow metadata
  -> Graph document
```

## 6. 修改现有对象

GET response 是读取 projection，可能包含 `id`、状态、masked credential、计算字段和其他只读字段。它不是 PUT payload。

修改对象时：

1. GET 当前完整对象；
2. 从 endpoint contract 确认可写字段；
3. 保留未修改的必需可写字段；
4. 修改目标字段；
5. 删除 `id`、状态、masked metadata 和其他只读字段；
6. PUT 完整可写 payload；
7. GET 回读并确认持久化结果。

需要特别处理的对象：

- Model Connection credential 是 write-only input，GET 中的 masked metadata 不能回写为 credential；
- Python-backed Component 的 source file 通过 File Manager 管理，不塞入普通 Component PUT；
- Workflow Graph 使用 `/draft`、`/validate` 和 `/graph` endpoint，不通过 Workflow metadata PUT 保存；
- API Server 的 API Key 使用 `keep`、`replace` 或 `clear` command，修改前先读取当前 configured 状态。

## 7. Discovery 失败

读取 HTTP status、structured error code、`detail` 和 request ID。

- `401` 或 `403`：检查 API domain、所需环境变量是否存在和 Authorization header 的变量引用；不要输出 credential value；
- `404`：检查 base URL、endpoint、active Repository 和 UUID；
- `409`：检查 Repository 状态、名称或 identity 冲突；
- `422`：检查 query、payload shape 或当前 contract；
- `5xx`：保留 request ID，检查服务日志和运行环境。

不要把 secret、完整用户消息或 host path 复制到诊断材料。

## 8. 本章完成结果

进入下一章前确认：

- health 和 readiness 成功；
- active Configuration Repository 已记录；
- Component Catalog 和 Workflow Node Catalog 已读取；
- configuration options 和目标完整对象已读取；
- 需要的 template identity 来自当前 catalog；
- reference ledger 已建立；
- 写入前已有的 Repository issue 已记录；
- 用户要求和当前实例事实之间的缺口已经列出。

下一步阅读[设计 Workflow](02-design-workflow.md)。
