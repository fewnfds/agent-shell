# Model Connection 与 Model Requirement

## Model Connection

Model Connection 是实例私有资源（instance-level Model Connection），在【模型 -> 模型连接】创建和维护；【配置库 / 全局 / 模型连接】复用同一个列表，编辑页仍位于【模型 / 模型连接】。它保存 LangChain Provider、`base_url`、具体 `model`、`provider_settings`、`model_settings`、`tool_choice`、`response_format` 以及 write-only `credential`。连接 YAML 位于 `data/config/model-connections/<uuid>.yaml`，凭据值只位于 `data/config/agent-shell.env`；API response 只返回 `masked` 或 `missing` 状态。

模型连接不属于 Configuration Repository，不进入配置 Bundle，也不提供下载。接口为：

- `GET/POST /api/model-connections`
- `GET/PUT/DELETE /api/model-connections/{id}`
- `POST /api/model-connections/{id}/copy`，body 为 `{"name":"<1-120 trimmed>"}`；重名返回 409 `model_connection_name_conflict`。
- `GET /api/model-requirements`，返回当前 Configuration Repository 的模型要求及绑定投影；
- `PUT /api/model-requirements/{id}/binding`，body 为 `{"connection_id":"<uuid>"}` 或 `{"connection_id":null}`，后者表示解绑。

模型连接表单沿用现有 Provider contract；`credential` 省略或为 `null` 时，Provider 与 `base_url` 均未变会复用已有 secret，其他变更会把状态设为 `missing` 并等待重新输入。`google_vertexai` 使用无 credential 配置。GET 返回的 `masked` 字段是只读状态；PUT 的 `credential` 接受 `null` 或新的 Key。
`name` 去除首尾空白后必须包含 1 到 120 个字符，并在实例内按大小写不敏感规则保持唯一。空白或超长名称返回 422 `model_connection_invalid`，重名返回 409 `model_connection_name_conflict`。

`provider_settings.streaming`首先决定模型调用是否提供 token delta。显式设为`false`时，运行时同时设置 LangChain BaseChatModel的`disable_streaming=true`，因此 LangGraph application streaming不会通过 auto-streaming重新开启该模型。Exception Retry的`force_non_streaming=true`可以在 Agent装配时把最终设置单向覆盖为关闭。这个上游设置只改变 delta何时可用；Agent Event Output仍统一接收 additive `start / delta / end`，非流式完整正文会成为一个合成 delta。

## Model Requirement

模型要求是代理组件中的可迁移 Component type `model-requirement`，payload 只包含名称和多行 `description`。`name` 去空白后为 1-120 个字符且在作用域内大小写不敏感唯一，`description` 为必填的 1-100000 字符文本；Main Agent 必须引用模型要求，Subagent 只能继承或替换，不能禁用该必选能力：

```json
{
  "name": "Reasoning model",
  "description": "Use a reasoning-capable model for planning and tool selection."
}
```

Main Agent 和 Subagent 通过模型要求 UUID 引用。模型要求进入 Bundle 闭包，但 Provider、具体 model、credential 和模型连接不会进入 Bundle。

## 模型映射

【模型 -> 模型映射】列表显示当前 Configuration Repository 的全部模型要求。每张卡标题为 `name`，折叠区显示 `description`，并从模型连接列表中显式选择绑定；一个连接可供多个要求复用。映射集中保存在单一实例文件 `data/config/model-bindings.yaml`，内部按 Repository UUID 分区，不随 Bundle 或整仓库下载导出。

导入后模型要求默认未绑定。页面、repository validation 和 Bundle preview 显示 warning；实际运行在 Agent 装配边界返回 `model_requirement_unbound`，不会启动模型调用。删除模型连接会清除相关 binding，不会自动替换。
请求开始装配时会捕获对应 Repository 的 binding、模型连接和 credential 视图；捕获后的模型资源修改只对后续请求生效。
