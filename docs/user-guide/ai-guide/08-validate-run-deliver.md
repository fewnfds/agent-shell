# 验证、运行与交付

本章验证current Main Agent或Workflow在当前实例中的配置、发现与真实运行结果，并形成交付记录。Workflow还需要Graph validation与publish步骤。

`/agent-shell/api/*` 使用 `AGENT_SHELL_MANAGEMENT_TOKEN`。`/compat/openai/v1/*` 使用 `AGENT_SHELL_API_KEY`。两类 credential 不能互换，并按[发现当前实例事实](01-discover-current-instance.md)的本地程序或运行平台注入边界使用，实际值不进入操作 Agent 上下文。

## 1. 验收顺序

```text
Repository validation
  -> [Workflow] 完整 candidate Graph validation
  -> [Workflow] publish并回读同一份 Graph document
  -> Model Mapping
  -> MCP Mapping
  -> Python dependency status
  -> API Server
  -> /compat/openai/v1/models
  -> one real invocation
  -> delivery
```

## 2. Repository validation

调用：

```text
GET /agent-shell/api/validation/repository
```

确认本次创建或修改的 Component、Subagent、Main Agent 和 Workflow reference 没有 error。

记录与本次任务无关的既有 issue，不为了清空整个 Repository 扩大修改范围。

## 3. Candidate Graph validation

准备一份完整 `WorkflowGraphDocumentV1`。它应与准备 publish 的 document 完全相同。

如果还没有保存 draft，先按[构建 Workflow Graph](05-build-workflow-graph.md)保存并回读，不在本章重复构造 draft payload。

然后把完整 document 作为 request body 调用 validation：

```http
POST /agent-shell/api/workflows/<workflow UUID>/validate
Content-Type: application/json

<complete WorkflowGraphDocumentV1>
```

`POST /validate` 验证 request body 中的 candidate，不会自动读取已保存 draft 作为请求内容。每次修改 Node、Edge、layout 或 reference 后，向 `/validate` 重新提交修改后的完整 document。

读取 response：

- `valid` 表示是否通过；
- `stage` 表示 validation stage；
- `issues[]` 返回一次发现的全部 issue；
- `severity` 区分 error 和 warning；
- `code`、`path`、`owner_id`、`owner_type` 和 `message` 用于定位 owner。

修正全部 `severity=error` issue。warning 允许 publish，但必须理解其运行影响。

不要通过删除业务必需 Node、降低用户要求或绕过 reference 让 validation 变绿。修复 issue 指向的 Graph wire、Component、package 或 Agent assembly owner。

## 4. Publish

`valid=true` 后，把同一份完整 Graph document 提交到：

```http
PUT /agent-shell/api/workflows/<workflow UUID>/graph
Content-Type: application/json

<complete WorkflowGraphDocumentV1>
```

publish endpoint 会再次执行完整 static validation。成功时原子保存 Graph，并设置 `enabled=true`。

失败时返回 422，不写入该 publish request 的 candidate，也不改变 request 开始前的 enabled state。读取完整 structured issue，修正 owner，再重新 validate 和 publish。

publish 后回读：

```text
GET /agent-shell/api/workflows/<workflow UUID>
GET /agent-shell/api/workflows/<workflow UUID>/graph
```

核对：

- Workflow `id` 和 `name`；
- `enabled=true`；
- runtime metadata；
- Node `id`、`type`、`type_version` 和 `config`；
- Edge ID、source/target和两端handle；
- layout Node key 与 Node ID 对应。

如果用户要求保持 draft，不调用 publish，并在交付中明确 `enabled=false` 和未执行真实 `/compat/openai/v1` invocation 的原因。

## 5. Model Mapping

Workflow 不装配模型。只要本次交付包含直接入口 Main Agent、Command-launched Agent、synchronous Subagent 或 Async Subagent 目标，就检查对应 Model Mapping。

读取：

```text
GET /agent-shell/api/model-requirements
GET /agent-shell/api/model-connections
```

检查每个直接运行或被引用的 Main Agent，以及其 synchronous Subagent 使用的 Model Requirement。Async Subagent 目标是另一份完整 Main Agent assembly，也需要自己的有效 binding。

用户先建立满足能力要求的 Model Connection。AI 根据 Requirement description 检查 tool calling、structured output、context window、multimodal input 和其他真实要求。

缺少 binding 时返回[配置 Agent](03-configure-agent.md)，按 Model Mapping 步骤提交用户选择的 Connection UUID。然后再次读取 Model Requirement projection，确认 binding 指向预期 Connection。

未绑定时不要发起真实 Agent invocation。运行 assembly 会返回 `model_requirement_unbound`。

## 6. MCP Mapping

Graph 中没有引用 MCP 的 Main Agent、Subagent 或 Command 时跳过本节。

读取：

```text
GET /agent-shell/api/mcp-requirements
GET /agent-shell/api/mcp-connections
```

沿可达 Main Agent、Subagent 和 Command 的 ordered `mcp_refs` 检查每个 MCP Requirement。用户先建立实际可用的 MCP Connection，再通过 `PUT /agent-shell/api/mcp-requirements/<requirement UUID>/binding` 提交用户选择的 `connection_id`。回读 Requirement projection，确认 binding 指向预期 Connection。

Connection 中每个 secret env/Header 的状态必须为 `masked`；`missing` 表示该 slot 尚无值。MCP secret 由 Agent Shell 解析，操作 Agent 不提取其实际值，也不要求用户在对话中粘贴 secret。未绑定、Connection 缺失、secret 缺失或 `include` 中的原始 Tool name 不存在都会在 Agent Graph 构造前失败，不应描述为已验证。

Management API 没有单独的“测试 MCP”入口。以一次覆盖目标 Agent/Command 路径的真实 Workflow invocation 验证 Tool discovery 和调用；Resource/Prompt 只有 Command 显式调用时才被读取，不会自动成为 Agent Tool。

## 7. Python dependency status

对全部已配置Main Agent assembly，以及enabled Workflow使用的Python-backed Component调用：

```text
GET /agent-shell/api/blocks/<type>/<component UUID>/python-package
```

处理：

- `ready`：继续；
- `restart_required`：重启 service，再次 GET；
- `failed`：根据 `dependency_error_code` 修正 `requirements.txt` 或兼容性问题。

没有额外 dependency 的 package 也应得到 `ready`。

static validation 不证明 Provider、third-party API、动态 import 或真实业务路径可用。只有一次真实 invocation 能覆盖 runtime path。

## 8. 准备 API Server

先读取当前状态：

```text
GET /agent-shell/api/api-server
```

response 只返回 API Key 是否 configured，不返回 secret value。

如果 API Key 已 configured，按第一章的认证边界取得 `AGENT_SHELL_API_KEY`，在同一本地程序或已注入该值的 HTTP client 中完成后续 `/compat/openai/v1/*` 调用。不要把它返回给操作 Agent，也不要因为 GET 不回显 secret 就自动替换它。

如果本地程序或运行平台无法取得 `AGENT_SHELL_API_KEY`，报告该 key 为 `missing`，并把真实 `/compat/openai/v1/*` 验证记录为未验证项。不要通过读取工具打开 secret store，也不要要求用户在对话中粘贴 API Key。

只有用户明确要求替换或当前尚未配置，并且本地执行边界已从对话之外取得新的 `AGENT_SHELL_API_KEY` 时，才用它构造 write-only value：

```http
PUT /agent-shell/api/api-server
Content-Type: application/json
```

```json
{
  "api_key": {
    "operation": "replace",
    "value": "<value injected from AGENT_SHELL_API_KEY>"
  }
}
```

`<value injected from AGENT_SHELL_API_KEY>` 只表示 client-side 注入位置，不能把这段占位文本按字面发送。构造和发送 request 时不记录 request body。变量缺失时，由用户在对话之外完成设置；AI 不生成、猜测或索取 secret。

`api_key.operation` 支持：

- `keep` 保留现有 key，且不接受 `value`；
- `replace` 使用新的非空、无空格 printable ASCII value；
- `clear` 清除 key，且不接受 `value`。

启动 API Server：

```text
POST /agent-shell/api/api-server/start
```

请求不需要 body。再次 GET，确认 `enabled=true` 和 `status="running"`。

API Key 只用于 `/compat/openai/v1/*`，不写入 Graph、Component、日志或交付报告。

## 9. 确认模型入口可发现

```http
GET /compat/openai/v1/models
Authorization: Bearer ${AGENT_SHELL_API_KEY}
```

确认`is_model_entry=true`的Main Agent name，或刚刚publish且选择作为模型入口的Workflow name出现在model list。

找不到时依次检查：

1. Main Agent是否`is_model_entry=true`，或Workflow是否同时`enabled=true`与`is_model_entry=true`；
2. API Server 是否 running；
3. 请求是否使用 `/compat/openai/v1` API Key；
4. 入口name是否与预期`model`完全一致。

`is_model_entry=true`的Main Agent和`enabled=true`且`is_model_entry=true`的Workflow出现在`/compat/openai/v1/models`；全部enabled Workflow都可以被其他Workflow Run调用。

## 10. 发起一次真实 invocation

使用精确Main Agent或Workflow入口name发起non-streaming request：

```http
POST /compat/openai/v1/chat/completions
Authorization: Bearer ${AGENT_SHELL_API_KEY}
Content-Type: application/json
```

```json
{
  "model": "entry-name",
  "messages": [
    {
      "role": "system",
      "content": "Follow the requested output format."
    },
    {
      "role": "user",
      "content": "Return exactly: workflow-ready"
    }
  ],
  "stream": false
}
```

测试输入必须覆盖本次任务的主要路径：

- Main Agent：确认AAP或其他输入owner把目标材料交给正确Agent，并得到Agent Event Output；
- Async Subagent：确认父 Agent 能 start 并返回完整 task ID，后续同一父 Thread 的新 Run 能 check/list；需要时覆盖 update 或 cancel，并确认 child 结果只在父 Agent 复述后进入公开 response；
- Command Workflow：确认预期State update、目标Node ID、独立Run调用、downstream completion和termination；
- MCP：确认目标 consumer 只看到或调用其 `mcp_refs` 允许的 Tool；Command 使用 Resource/Prompt 时同时验证对应返回和 State 投影；
- 跨 Workflow 调用：确认 operation 与官方 Run identity、`check/list/join/cancel`、失败、主动取消以及 result handoff；
- Workflow Event Output：确认需要公开的 Workflow event 被正确 projection。

纯 Command Workflow 没有可投影文本时，可以返回合法空内容。验收依据是所选root Graph的预期行为，不强制要求 Assistant text。

## 11. Invocation 失败

保留 HTTP status、structured error code、request ID 和非敏感 issue。按 owner 定位：

1. 检查所选Main Agent的model entry，或Workflow的enabled/model entry状态；
2. 检查 Model Mapping 与 MCP Mapping；
3. 检查 MCP secret slot、Tool discovery 和 consumer allowlist；
4. 检查 Python dependency status；
5. 检查 Provider endpoint、model capability 和 credential missing state；
6. 通过 `GET /agent-shell/api/workflow-lifecycles` 找到当前 Lifecycle；
7. 在【系统 / 日志中心】按 `request_id`、`lifecycle_id` 或 `run_id` 定位运行诊断，并按需下载对应异常详情附件；
8. 根据诊断关联的 subject、Workflow Node、`node_invocation_id`、`exception_type` 和稳定错误码修正一个 owner；
9. 使用同一个可复现输入重试。

运行监控页面按 Lifecycle 浏览本次请求已登记的全部官方 Run，包括由关联 Middleware 登记的 Async Subagent child；选择 Run 后可查看原始 Run 对象、Assistant Graph、Thread latest State 和最近 State history。父 Agent 仍通过`async_tasks`与五个 task 工具管理 child。页面通过刷新按钮重新读取公共 API，不从日志推演 Edge、Node attempt 或跨资源 Timeline。运行失败继续结合调用方 structured error 和日志中心诊断定位。

常见 HTTP 范围：

- `401` 或 `403`：credential domain、Authorization header 或访问范围；
- `404`：endpoint、Repository、UUID 或 Workflow name；
- `409`：名称冲突、未绑定 Model/MCP Requirement、缺少 MCP secret/Tool、operation conflict 或当前状态不允许；
- `422`：payload、Graph、package 或 assembly 不符合 contract；
- `5xx`：Runtime、Provider、外部服务或系统资源失败。

诊断材料不复制 Provider secret、完整用户私密消息、package source、traceback 或 host path。management-only 本地异常附件按安全与部署文档处理。

Lifecycle 和 Run 观测见[Runtime observability](../runtime-observability.md)。

## 12. Configuration Bundle import

如果当前任务是导入 Bundle，先按[管理配置库](../configuration-library.md)完成 export、preview、resolution、trusted-code review 和 import。

import 后：

1. 记录新 target UUID；
2. 重新建立 Model Mapping；
3. 重新建立 MCP Mapping；
4. 完成 Filesystem path binding；
5. 审查 Python source、`requirements.txt` 和 Skill package；
6. 回到本章执行 Repository validation；
7. 对完整 Graph document执行 candidate validation；
8. 显式 publish；
9. 检查 dependency、`/compat/openai/v1/models` 和真实 invocation。

Configuration UUID 在导入后改变。Graph-local Node ID 和 Edge ID 保持不变。Model/MCP Connection、binding 和 secret 不随 Bundle 迁移。

## 13. 交付报告

使用简短报告：

```text
Workflow
- name: <workflow name>
- id: <workflow UUID>
- enabled: true | false

Created or reused
- Main Agent: <name and UUID, or not used>
- Model Requirement: <name, UUID and capability summary, or not used>
- Model Connection: <user-managed name or UUID, or pending>
- MCP Requirement/Connection: <names and UUIDs, not used or pending>
- Components: <type, name and UUID>

Validation
- Repository validation: <result>
- Graph validation: <valid and stage>
- Dependency status: <ready, not used or pending>
- MCP Mapping and invocation: <verified, not used or pending>
- /compat/openai/v1/models: <found, not applicable or not checked>
- Real invocation: <input summary and observable result>

Not tested or user action
- <remaining item and reason>
```

报告可以包含 Configuration UUID 和非敏感名称。不要包含 token、API Key、Provider credential、完整私密消息或用户文件正文。

## 14. 完成判定

与用户需求相符的真实 invocation 成功，并且可观察结果符合预期时，本轮配置任务具备运行验收证据。

以下情况可以记录为未验证项后交付：

- 用户尚未提供 Model Connection 或 Provider credential；
- 用户尚未提供 MCP Connection、binding 或所需 secret；
- 本地程序或运行平台无法取得 `AGENT_SHELL_MANAGEMENT_TOKEN` 或 `AGENT_SHELL_API_KEY`；
- 外部 API、文件或业务环境不可访问；
- 用户要求保持 Workflow draft；
- 当前任务只授权文档或静态配置检查。

未验证项必须说明阻塞条件和用户下一步，不能描述为已通过。
