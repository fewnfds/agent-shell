# 发现当前实例事实

本章适用于所有配置任务。在创建或修改任何对象前完成本章。

完成结果是一份当前实例的 reference ledger，以及继续设计 Workflow 所需的 Catalog、现有对象和配置状态。

## 1. 确认地址、登录方式和 credential domain

默认 Management API base URL 是 `http://127.0.0.1:19100`。实际地址以用户提供的运行实例为准。

Agent Shell 使用两类 credential：

- `/agent-shell/api/*` 使用 management token，负责配置、validation、API Server 控制和 Lifecycle 管理；
- `/compat/openai/v1/*` 使用独立 API Key，负责列出和运行 `enabled=true` 且 `is_model_entry=true` 的 Workflow。

Management API 没有提交密码后再换取 token 的登录接口。首次启动设置的管理密码就是 `/agent-shell/api/*` 使用的 management Bearer credential，在实例 secret store 中的名称是 `AGENT_SHELL_MANAGEMENT_TOKEN`。

`GET /agent-shell/api/health` 是匿名存活探测。其他 `/agent-shell/api/*` 请求通常需要：

```http
Authorization: Bearer ${AGENT_SHELL_MANAGEMENT_TOKEN}
```

`/compat/openai/v1/*` 请求需要：

```http
Authorization: Bearer ${AGENT_SHELL_API_KEY}
```

`${...}` 在本指南中表示 HTTP client 在本地执行边界注入值，不是要按字面发送的 header 内容。两类 credential 不能互换：`AGENT_SHELL_MANAGEMENT_TOKEN` 只用于 `/agent-shell/api/*`，`AGENT_SHELL_API_KEY` 只用于 `/compat/openai/v1/*`。

实际值位于 `<data-root>/config/agent-shell.env`。默认 data root 是 `<application-home>/data`；使用 `--data-dir` 启动时以该参数为准。仓库根目录的 [`.env.example`](../../../.env.example) 只说明当前 key 格式，不参与运行，也不保存实际值。

用户已授权操作同一台机器上的实例时，操作 Agent 可以让本地程序使用 dotenv parser 加载所需认证 key，并在同一进程中完成 HTTP 请求。操作 Agent 不得通过文件读取工具、`cat`、`Get-Content` 或编辑器打开实际 secret store；不得让 dotenv mapping、secret value、Authorization Header、HTTP debug/trace 或含 secret 的异常进入工具输出；不得把值展开到命令参数、临时文件、对话、任务材料或交付报告。远程或隔离执行环境不能访问实例 secret store 时，由运行平台在对话之外注入 credential；缺失时只报告 key name 和 `missing` 状态。

以下跨平台 Python 示例只把 `/agent-shell/api/readiness` response 返回给操作 Agent。其他语言使用相同边界：dotenv parser -> 进程内局部变量 -> HTTP client Header -> 非敏感 response。

```python
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import dotenv_values


data_root = Path("<data-root>")
base_url = "http://127.0.0.1:19100"
token = dotenv_values(
    data_root / "config" / "agent-shell.env",
    interpolate=False,
).get("AGENT_SHELL_MANAGEMENT_TOKEN")
if not token:
    raise SystemExit("AGENT_SHELL_MANAGEMENT_TOKEN is missing")

request = Request(
    base_url + "/agent-shell/api/readiness",
    headers={"Authorization": "Bearer " + token},
)
with urlopen(request) as response:
    print(response.read().decode("utf-8"))
```

不要打印 `token`、dotenv mapping、`request.headers` 或完整 request。Model Connection credential、MCP secret 和 LangSmith API Key 由 Agent Shell 自己解析和使用；操作 Agent 通过 Management API 的 `masked`、`missing`、configured 状态及真实 Workflow invocation 验证它们，不从 secret store 提取这些值。

先调用：

```text
GET /agent-shell/api/health
GET /agent-shell/api/readiness
```

health 失败时先解决地址或服务问题。readiness 失败时读取 structured response，不继续写配置。

## 2. 按顺序读取事实

依次调用：

1. `GET /agent-shell/api/configuration-repositories`，记录 active Repository；
2. `GET /agent-shell/api/catalog`，读取 Component type、required flag、Subagent policy 和 editor default；
3. `GET /agent-shell/api/workflow-node-catalog`，读取 Node type、version、`config_schema`、input handle 和 output handle；
4. `GET /agent-shell/api/configuration-options`，取得当前 Repository 的引用摘要；
5. 读取准备复用、修改或排查的完整对象；
6. 需要 Python-backed component 时，读取对应 template catalog；
7. 需要 Agent Node 时，读取 Model Requirement、Model Connection 和 binding 状态；Agent、Subagent 或 Command 使用 MCP 时，同时读取 MCP Requirement、MCP Connection 和 binding 状态；
8. `GET /agent-shell/api/validation/repository`，记录写入前已有的 error 和 warning。

不要根据模型记忆猜测 Catalog key、template revision、UUID、Node handle 或 active Repository。

## 3. 常用事实入口

- `GET /agent-shell/api/catalog` 返回当前 Component contract；
- `GET /agent-shell/api/workflow-node-catalog` 返回当前 Node 和 endpoint contract；
- `GET /agent-shell/api/configuration-options` 返回 active Repository identity、revision 和可引用对象摘要；
- `GET /agent-shell/api/blocks/{type}` 返回某类 Component；`GET /agent-shell/api/blocks/{type}/{id}` 返回一条完整记录；
- `GET /agent-shell/api/main-agents` 和 `GET /agent-shell/api/subagents` 返回 Agent configuration；
- `GET /agent-shell/api/workflows` 返回全部 Workflow；可以通过通用 collection 参数读取 summary、搜索或分页；
- `GET /agent-shell/api/model-connections` 返回当前实例私有 Model Connection 的 masked 或 missing projection；
- `GET /agent-shell/api/model-requirements` 返回当前 Repository 的 Model Requirement 和本机 binding projection；
- `GET /agent-shell/api/mcp-connections` 返回当前实例私有 MCP Connection；每个 secret env/Header 只显示 `masked` 或 `missing`；
- `GET /agent-shell/api/mcp-requirements` 返回当前 Repository 的 MCP Requirement 和本机 binding/Connection projection；
- `GET /agent-shell/api/skills` 返回可选择的 Skill Template；
- `GET /agent-shell/api/python-package-templates/{kind}` 返回 Python template catalog；
- `GET /agent-shell/api/validation/repository` 返回当前 Repository validation report。

当前 Python template kind 包括 `custom-tool`、`middleware`、`agent-event-output`、`workflow-event-output` 和 `command`。仍应以当前实例 endpoint response 为准。

Model Connection 与 MCP Connection 不属于 Configuration Repository，也不进入 Configuration Bundle。Model Requirement、MCP Requirement、其他 Component、Agent 和 Workflow 属于 active Repository。

## 4. 正确读取 collection

Component、Main Agent、Subagent 和 Workflow collection 支持两种表示：

- 不提交 `view`、`q`、`offset`、`limit` 时，response 是完整对象数组，不会隐式分页；
- 只要显式提交上述任一 collection 参数，response 就使用 `items`、`total`、`repository_id`、`repository_revision` envelope。

`view=full` 返回完整 item projection，`view=summary` 返回引用和列表所需字段。只需要 UUID 和候选引用时，优先读取 `/agent-shell/api/configuration-options`。只修改一个对象时，优先读取单项 GET。

`repository_revision` 表示当前进程内的 Repository 内容一致性身份，不是发布版本或历史版本。

## 5. 建立 reference ledger

在 AI 当前工作记忆中维护简短 ledger。它不写入 Workflow State。

```json
{
  "active_repository_id": "<repository UUID>",
  "components": {
    "model_requirement": null,
    "mcp_requirements": [],
    "agent_event_output": null,
    "command": null,
    "workflow_event_output": null,
    "response_stream_scheduling": null
  },
  "agents": {
    "main": null,
    "subagents": []
  },
  "workflow": {
    "id": null,
    "name": null
  },
  "model_binding": {
    "requirement_id": null,
    "connection_id": null
  },
  "mcp_bindings": {
    "<requirement UUID>": "<connection UUID>"
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
- MCP Connection 的 secret env/Header value 是 write-only input；更新时只提交新的 secret value，或保留对应 `masked|missing` 状态，不能把状态文本当作 secret value；
- Python-backed Component 的 source file 通过 File Manager 管理，不塞入普通 Component PUT；
- Workflow Graph 使用 `/draft`、`/validate` 和 `/graph` endpoint，不通过 Workflow metadata PUT 保存；
- API Server 的 API Key 使用 `keep`、`replace` 或 `clear` command，修改前先读取当前 configured 状态。

## 7. Discovery 失败

读取 HTTP status、structured error code、`detail` 和 request ID。

- `401` 或 `403`：检查 API domain、本地程序或运行平台能否取得所需 credential，以及 Authorization header 的 key 引用；不要输出 credential value；
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
- 目标运行路径使用 MCP 时，相关 Connection、Requirement、binding 与 secret slot 状态已读取；
- 需要的 template identity 来自当前 catalog；
- reference ledger 已建立；
- 写入前已有的 Repository issue 已记录；
- 用户要求和当前实例事实之间的缺口已经列出。

下一步阅读[设计 Workflow](02-design-workflow.md)。
