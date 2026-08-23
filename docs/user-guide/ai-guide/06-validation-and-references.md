# Validation、enabled 与真实 invocation

配置完成后按有限 checklist 验收：

以下 `/api/*` 请求使用 management token，`/v1/*` 请求使用独立 API Key；两种 credential 不能互换。

1. `GET /api/validation/repository`，确认本次创建的 component 和 Agent 没有 error。
2. `POST /api/workflows/{id}/validate` 提交完整 candidate Graph document，检查返回的 `valid`、`stage` 和 `issues[]`，修正全部 `severity=error` 的问题。
3. `PUT /api/workflows/{id}/graph` 执行完整校验并原子保存 Graph，同时设置 `enabled=true`；校验失败返回 422 且不落盘。成功后用 `GET /api/workflows/{id}` 核对 Workflow metadata 中的 `id`、`enabled` 和 `workflow_role`，再用 `GET /api/workflows/{id}/graph` 核对 `definition.nodes[].id/type/config`、`definition.edges[].source_handle/target_handle`、`branch_key`/`dispatch_key` 与 `layout.nodes` key。
4. 通过 `PUT /api/api-server` 设置独立 API Key；management token 与 inference API Key 属于两个 credential domain：

```json
{
  "api_key": {"operation": "replace", "value": "REPLACE_WITH_PRINTABLE_ASCII_WITHOUT_SPACES"},
  "max_initial_messages": 1000
}
```

`api_key.operation` 可为 `keep`、`replace` 或 `clear`；`replace` 接受非空、无空格的可打印 ASCII `value`。`max_initial_messages` 使用正整数，默认值为 `1000`。

5. `POST /api/api-server/start`，请求不需要 body。
6. 使用 API Key 调用 `GET /v1/models`，确认 Workflow name 出现。
7. 使用同一 name 发起一次 non-streaming `/v1/chat/completions` invocation，确认 Workflow 执行并返回 expected result。

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

配置保存成功表示 persistence 完成；真实 invocation 会继续验证 Graph reference、Python extension、Provider 和 output script。纯 Command/Task Dispatcher Workflow 同样可以 invoke；可投影事件集合为空时返回合法空内容。

配置 Bundle import 成功后，新 UUID 配置和资产已原子持久化。后续检查顺序是：在模型映射页为所有 Model Requirement 绑定模型连接；按 preview 完成绝对 mapped path 与 virtual source path 的显式重绑，并在报告 `filesystem_relative_target_missing` 时修正对应 data-root-relative 目录；审查 trusted-code warning 以及随新 owner UUID 重建的 Skill 私有包和 Python source/requirements；运行 repository validation；最后对 disabled Workflow 提交 candidate Graph validation 并显式 publish。后续调用使用返回的 target UUID；Workflow Node/Edge ID 始终是 Graph-local key。

## 详细文档

- 所有代理组件及 required/inheritance policy：[代理组件](../capabilities.md)
- Main Agent、Subagent、Workflow 语义：[Workflow、Main Agent 与 Subagent](../configuration-workflow.md)
- WIC 与前序 invocation 读取：[Workflow Input Context](../workflow-input-context.md)
- Python package、template、dependency 和 loading：[文件化 Python 扩展](../middleware-packages.md)
- Command Node 完整 contract：[Command Node](../../wizard-pages/command-config.md)
- Task Dispatcher 完整 contract：[Task Dispatcher](../../wizard-pages/task-dispatcher-config.md)
- Agent Event Output 稳定 event field：[Agent Event Output](../../wizard-pages/agent-event-output-config.md)
- Workflow Event Output field：[Workflow Event Output](../../wizard-pages/workflow-event-output-config.md)
- OpenAI-compatible Run entry point：[API Server](../api-server.md)
- background Run、Lifecycle cleanup 与 multi-Run semantics：[使用 background Run](05-background-runs.md)
- Debug thread、checkpoint 与 log boundary：[Runtime observability](../runtime-observability.md)
- secret 与远程访问边界：[安全与部署](../../security-and-deployment.md)

Agent Shell 使用 Deep Agents 官方 assembly 和 LangGraph Graph API。官方 context engineering 把始终相关的约定放在 concise prompt 中，由 WIC/Skill 按需加载 task-specific material，把长且独立的工作交给描述清晰的 Subagent，并把 large result 放入 shared Filesystem 后按需读取。参考 [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering)、
[Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) 和[Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)。
