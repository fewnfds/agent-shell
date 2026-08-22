# 模型连接与模型要求

## 模型连接

模型连接是实例私有资源，在【模型 -> 模型连接】创建和维护；【配置库 -> 系统 -> 模型连接】与【系统 -> 模型连接】复用同一个列表。它保存 LangChain Provider、`base_url`、具体 `model`、Provider 请求参数以及 write-only `credential`。连接 YAML 位于 `data/config/model-connections/<uuid>.yaml`，凭据实际值只位于 `data/config/agent-shell.env`；普通 API 响应只返回 `masked` 或 `missing` 状态。

模型连接不属于 Configuration Repository，不进入配置 Bundle，也不提供下载。接口为：

- `GET/POST /api/model-connections`
- `GET/PUT/DELETE /api/model-connections/{id}`
- `POST /api/model-connections/{id}/copy`

模型连接表单沿用现有 Provider contract；`credential: null` 在 Provider 与 Base URL 未变时保留已有 secret。
`name` 去除首尾空白后必须包含 1 到 120 个字符，并在实例内按大小写不敏感规则保持唯一。空白或超长名称返回 422 `model_connection_invalid`，重名返回 409 `model_connection_name_conflict`。

## 模型要求

模型要求是代理组件中的可迁移 Component type `model-requirement`，payload 只包含名称和多行 `description`：

```json
{
  "name": "Reasoning model",
  "description": "Use a reasoning-capable model for planning and tool selection."
}
```

Main Agent 和 Subagent 通过模型要求 UUID 引用。模型要求进入 Bundle 闭包，但 Provider、具体 model、credential 和模型连接不会进入 Bundle。

## 模型映射

【模型 -> 模型映射】递归显示当前 Configuration Repository 的全部模型要求。每张卡显示 description，并从模型连接列表中显式选择绑定；一个连接可供多个要求复用。同一仓库的映射保存在 `data/config/model-bindings.yaml`，不随 Bundle 导出。

导入后模型要求默认未绑定。页面和全局 repository validation 显示 warning；实际运行在 Agent 装配边界返回 `model_requirement_unbound`，不会启动模型调用。删除模型连接会清除相关 binding，不会自动替换。
请求开始装配时会捕获对应 Repository 的 binding、模型连接和 credential 视图；捕获后的模型资源修改只对后续请求生效。
