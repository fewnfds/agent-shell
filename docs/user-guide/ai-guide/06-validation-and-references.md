# Validation、publish 与真实 invocation

本章把配置工作收敛为一次有限验收。目标是证明 current Workflow 在当前实例中可以被发现并真实运行，然后停止继续扩展。

`/api/*` 请求使用 management token；`/v1/*` 请求使用独立 API Key。两类 credential 不能互换。

## 1. 有限验收顺序

```text
repository validation
  -> candidate Graph validation
  -> publish
  -> Model Mapping
  -> dependency status
  -> API Server
  -> /v1/models
  -> one real invocation
  -> success and stop
```

## 2. Repository validation

调用：

```http
GET /api/validation/repository
Authorization: Bearer <management token>
```

确认本次创建或修改的 component、Subagent、Main Agent 和 Workflow reference 没有 error。记录与本次工作无关的既有 issue，不要为了清空整个 Repository 而扩大修改范围。

## 3. Candidate Graph validation

先保存 draft，再对准备发布的完整 Graph document 执行只读 validation：

```text
PUT  /api/workflows/{id}/draft
POST /api/workflows/{id}/validate
```

读取 response 的 `valid`、`stage` 和 `issues[]`。每个 issue 的 `severity`、`code`、`path`、`owner_id` 和 `message` 用于定位 owner。修正全部 `severity=error`；warning 允许发布，但应理解其运行影响。

不要通过删除业务必需字段、减少 topology 或绕过 reference 来让 validation 变绿。修复 issue 指向的 Graph wire、component、package 或 Agent assembly。

## 4. Publish 并回读

`valid=true` 后发布：

```http
PUT /api/workflows/<workflow UUID>/graph
Authorization: Bearer <management token>
Content-Type: application/json

<complete WorkflowGraphDocumentV1>
```

该 endpoint 会再次执行完整 validation。成功时原子写入 Graph document 并设置 `enabled=true`；失败时返回 422，不写 candidate，也不改变原 enabled state。

发布后执行两次回读：

1. `GET /api/workflows/{id}`：核对 `id`、`name`、`enabled=true` 和 `workflow_role=parent`；
2. `GET /api/workflows/{id}/graph`：核对 Node `id/type/config`、Edge `source_handle/target_handle`、`branch_key` / `dispatch_key` 和 layout Node key。

## 5. Model Mapping

Graph 包含 Agent Node 时，读取 `GET /api/model-requirements`，检查每个可达 Agent 使用的 Model Requirement binding。

用户先建立 Model Connection。AI 根据 Requirement description 检查其能力是否满足 tool calling、structured output、context window、multimodal input 或其他真实要求，再提交 binding：

```http
PUT /api/model-requirements/<requirement UUID>/binding
Authorization: Bearer <management token>
Content-Type: application/json

{"connection_id":"<model connection UUID>"}
```

纯 Command/Task Dispatcher Workflow 没有 Agent Node，可以跳过 Model Mapping。

## 6. Python dependency status

对 enabled Workflow 可达的 Python-backed component 调用：

```text
GET /api/blocks/{type}/{id}/python-package
```

检查 `dependency_status`：

- `ready`：可以继续；
- `restart_required`：重启 service，再次 GET；
- `failed`：根据 `dependency_error_code` 修正 `requirements.txt` 或兼容性问题。

没有额外 dependency 的 package 也应得到 `ready`。不要根据一次 static validation 推断 Provider、third-party API 或动态 import 已经可用；真实 invocation 才覆盖 runtime path。

## 7. 准备 API Server

通过 Management API 配置独立 API Key：

```http
PUT /api/api-server
Authorization: Bearer <management token>
Content-Type: application/json

{
  "api_key": {
    "operation": "replace",
    "value": "REPLACE_WITH_PRINTABLE_ASCII_WITHOUT_SPACES"
  },
  "max_initial_messages": 1000
}
```

`api_key.operation` 可以是 `keep`、`replace` 或 `clear`；`replace` 接受非空、无空格的 printable ASCII `value`。`max_initial_messages` 使用正整数，默认值是 `1000`。

启动 API Server：

```http
POST /api/api-server/start
Authorization: Bearer <management token>
```

请求不需要 body。API Key 只用于 `/v1/*`，不要把它写入 Graph、component 或交付报告。

## 8. 确认 Workflow 可发现

```http
GET /v1/models
Authorization: Bearer <API Key>
```

确认刚刚 publish 的 parent Workflow name 出现在 model list。找不到时依次检查：

1. Workflow 是否 `enabled=true`；
2. `workflow_role` 是否为 `parent`；
3. API Server 是否已经 start；
4. 当前请求是否使用 `/v1` API Key；
5. Workflow name 是否与调用时的 `model` 完全一致。

## 9. 发起一次真实 invocation

使用同一 Workflow name 发起一次 non-streaming request：

```http
POST /v1/chat/completions
Authorization: Bearer <API Key>
Content-Type: application/json

{
  "model": "ai-workflow",
  "messages": [
    {"role": "system", "content": "Follow the requested output format."},
    {"role": "user", "content": "Return exactly: workflow-ready"}
  ],
  "stream": false
}
```

测试输入应覆盖本次改动的主要路径：

- Agent Workflow：确认动态输入确实进入 target Agent，并得到 Agent Event Output；
- Command Workflow：确认 expected branch、State update 和 termination；
- Task Dispatcher Workflow：确认 task 生成、worker input 和下游完成语义；
- background Run Workflow：确认 handle 持久化、check、业务 exit 和可选 finalizer；
- Workflow Event Output：确认需要公开的 event 被正确投影。

可投影事件集合为空时，纯 Command/Task Dispatcher Workflow 可以返回合法空内容。验收应根据该 Workflow 的预期输出判断，不强行要求 Assistant text。

## 10. Invocation 失败时的定位顺序

保留 HTTP response、structured error code 和 request ID，然后按 owner 定位：

1. 再次检查 Workflow enabled state 和 Model Mapping；
2. 检查 Python package `dependency_status`；
3. 检查 Provider endpoint、model capability 和 credential missing 状态；
4. 通过 `GET /api/workflow-lifecycles` 找到 current Lifecycle；
5. 读取 Lifecycle detail、events 和对应 Run；
6. 根据失败的 `run_id`、Node invocation、event type 和 checkpoint 修正一个 owner；
7. 重试同一个最小输入。

Lifecycle 和 Run 观测 endpoint 见[使用 background Run](05-background-runs.md#6-lifecycle-management-api)与[Runtime observability](../runtime-observability.md)。诊断材料中不复制 Provider secret、完整用户私密消息或 host path。

## 11. 成功后停止

一次最接近用户需求的真实 invocation 成功，并且可观察结果符合预期后，本轮验收完成。不要因为存在更多可选 Node、Middleware、测试输入或优化方向继续扩展配置。

以下情况可以明确列为未验证项后交付：

- 用户尚未提供 Model Connection 或 Provider credential；
- 外部 API、文件或业务环境当前不可访问；
- 用户要求保持 Workflow draft；
- 当前任务只授权文档或静态配置检查。

未验证项需要说明阻塞条件和用户下一步，不能描述为已通过。

## 12. Configuration Bundle import 后的恢复

Bundle import 成功后，新 UUID 配置和资产已经原子持久化。按以下顺序恢复运行：

1. 记录 import response 中的 target UUID；
2. 在导入目标实例中为所有 Model Requirement 建立 Model Mapping；
3. 按 preview resolution 完成 Filesystem absolute mapped path 和 virtual source path binding；
4. 处理 `filesystem_relative_target_missing` 等 path issue；
5. 审查 trusted-code warning、Python source、`requirements.txt` 和 Skill 私有 package；
6. 运行 repository validation；
7. 对 disabled Workflow 执行 candidate Graph validation；
8. 显式 publish；
9. 完成 `/v1/models` 与一次真实 invocation。

Configuration UUID 在导入后改变；Node/Edge ID 是 Graph-local key，保持不变。Model Connection 和 credential 不随 Bundle 迁移。

## 13. 交付报告模板

```text
Workflow
- name: <workflow name>
- id: <workflow UUID>
- role: parent
- enabled: true | false

Created or reused references
- Main Agent: <name, UUID, or not used>
- Model Requirement: <name, UUID, capability summary, or not used>
- Model Connection: <user-managed connection name/UUID, or pending>
- Python components: <type, name, UUID>

Validation
- repository validation: <result>
- Graph validation: <valid/stage>
- dependency status: <ready/not used/pending>
- /v1/models: <found/not checked>
- real invocation: <input summary and observable result>

Not tested / user action
- <remaining item and reason>
```

报告可以包含 configuration UUID 和非敏感名称；不包含 token、API Key、Provider credential、完整私密消息或用户文件正文。

## 14. 详细文档

- 所有 Agent component 及 required/inheritance policy：[代理组件](../capabilities.md)
- Main Agent、Subagent、Workflow 语义：[Workflow、Main Agent 与 Subagent](../configuration-workflow.md)
- AAP 与 upstream invocation 读取：[Agent Additional Prompt](../agent-additional-prompt.md)
- Python package、template、dependency 和 loading：[文件化 Python 扩展](../middleware-packages.md)
- Command Node contract：[Command Node](../../wizard-pages/command-config.md)
- Task Dispatcher contract：[Task Dispatcher](../../wizard-pages/task-dispatcher-config.md)
- Agent Event Output field：[Agent Event Output](../../wizard-pages/agent-event-output-config.md)
- Workflow Event Output field：[Workflow Event Output](../../wizard-pages/workflow-event-output-config.md)
- OpenAI-compatible Run entry point：[API Server](../api-server.md)
- background Run 与 Lifecycle cleanup：[使用 background Run](05-background-runs.md)
- checkpoint 与日志边界：[Runtime observability](../runtime-observability.md)
- secret 与远程访问边界：[安全与部署](../../security-and-deployment.md)

Agent Shell 使用 Deep Agents 官方 assembly 和 LangGraph Graph API。context engineering 可以把稳定约定放入 concise System Prompt，由 AAP/Skill 选择 task-specific material，把独立工作交给描述清晰的 Subagent，并把 large result 写入共享 Filesystem 后按 reference 读取。参考 [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering)、[Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) 和 [Custom Middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)。
