# 模型

模型连接与配置中的模型要求是两个独立概念。前后端统一使用 `Model Connection` / `model-connection` contract。

## 模型连接

【配置库 / 全局 / 模型连接】提供模型连接的通用列表，提供查看、编辑、复制和删除，不提供配置下载。编辑动作进入【模型 / 模型连接】(`/models/connections`)，该页面直接复用组件配置编辑框架：选择已有连接后自动载入，底部提供复制、删除、新建和保存，右侧显示服务端校验。

模型连接保存 `provider`、`base_url`（服务地址）、`model`、`credential`、`provider_settings`、`model_settings`、`tool_choice` 和 `response_format`，按当前 `ModelConnectionBlock` 校验；`provider` 限本版本内置 Provider，`base_url` 必须是 http/https 且不含 query、fragment 或 userinfo。凭据实际值只保存于实例 env，列表和编辑响应不会回显明文。它是系统私有资源，不进入 Configuration Repository，也不会被配置 Bundle 或整仓库下载导出。

连接 YAML 位于 `data/config/model-connections/<uuid>.yaml`，实际 secret 位于 `data/config/agent-shell.env` 的 `AGENT_SHELL_MODEL_<UUID_WITHOUT_HYPHENS>_API_KEY`；普通 API 返回 `credential.status` 为 `masked` 或 `missing`。编辑时 `credential: null` 在 Provider 与 `base_url` 保持不变时保留旧 Key；`google_vertexai` 使用无 credential 配置。名称去空白后须为 1-120 个字符且在实例内大小写不敏感唯一；格式错误返回 422 `model_connection_invalid`，重名返回 409 `model_connection_name_conflict`。

## 模型映射

在【模型 / 模型映射】(`/models/mapping`)中查看当前 Configuration Repository 的全部模型要求。`GET /api/model-requirements` 返回 `{id,name,description,binding,connection}` 投影；通过 `PUT /api/model-requirements/{requirement_id}/binding` 提交 `{connection_id: string|null}`，`null` 表示解绑。导入配置后，要求默认未绑定；根据要求的 name 与 description 选择模型连接并保存。

同一个模型连接可以绑定多个模型要求。映射文件为 `data/config/model-bindings.yaml`，按 Repository UUID 分区。`binding==null` 或 `connection==null` 均显示 warning；repository validation 和运行装配返回 `model_requirement_unbound`。切换 Configuration Repository 后，模型连接列表保持不变，映射按仓库分别保存。
请求进入 `POST /v1/chat/completions` 时会原子捕获所用 Repository 的配置和 `ModelResourceSnapshot`（连接、YAML、env 与 bindings）。捕获完成后修改或删除连接、解除绑定或切换 Repository，只对后续请求生效。

## 代理组件中的模型要求

“代理组件 -> 模型要求”只编辑可迁移的 name 与多行 description，对应 Component type `model-requirement`（创建接口为 `POST /api/blocks/model-requirement`）。Main Agent 和 Subagent 引用模型要求 UUID；Provider、endpoint 和 credential 由本机模型连接维护。导出和导入配置时不会携带本机凭据，目标实例可以用自己的模型连接完成映射。
