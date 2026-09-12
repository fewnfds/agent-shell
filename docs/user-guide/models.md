# Model Connection、Model Requirement 与 Model Mapping

模型连接与配置中的模型要求是两个独立概念。前后端统一使用 `Model Connection` / `model-connection` contract。

## Model Connection

【配置库 / 全局 / 模型连接】提供模型连接的通用列表，提供查看、编辑、复制和删除，不提供配置下载。编辑动作进入【模型 / 模型连接】(`/models/connections`)，该页面直接复用组件配置编辑框架：选择已有连接后自动载入，底部提供复制、删除、新建和保存，右侧显示服务端校验。

模型连接保存 `provider`、`base_url`（服务地址）、`model`、`credential`、`provider_settings`、`model_settings`、`tool_choice` 和 `response_format`，按当前 `ModelConnectionBlock` 校验；`provider` 限本版本内置 Provider，`base_url` 必须是 http/https 且不含 query、fragment 或 userinfo。凭据实际值只保存于实例 env，列表和编辑响应不会回显明文。它是系统私有资源，不进入 Configuration Repository，也不会被配置 Bundle 或整仓库下载导出。

当前开发测试主要覆盖 OpenAI-compatible（Chat Completions）、OpenAI Responses API 和 DeepSeek。其他 Provider 为 TBD，尚未经过大范围验证，实际可用性取决于 Provider integration、模型和上游端点。

Provider 出站网络由【系统 / 系统配置 / Provider Network】统一管理。标准 HTTPX 与 curl-cffi 浏览器兼容线路可以切换；`curl-cffi` 始终随软件安装，选择 HTTPX 表示 Provider 请求不经过它。系统不会在两条线路之间自动失败重试。HTTP version、TLS、自定义 CA、显式 proxy 与普通默认 Header 的完整共享 transport 当前用于 OpenAI、DeepSeek、xAI 和模型目录读取；Anthropic 只接收全局 Header 与显式 proxy，Google GenAI / Vertex AI 只接收全局 Header。

全局 Header 是 `system.yaml` 中可读取的普通配置，适合 `x-opencode-session` 等非 credential 参数。API Key 仍使用 Model Connection credential。模型连接的 `model_settings.extra_headers` 继续作为请求级设置，并按 Header 名称大小写不敏感地覆盖全局同名值。默认 `User-Agent` 为 `Agent-Shell/<version>`；需要自定义 Agent Shell 的 HTTP client identity 时，在全局 Header 中添加 `User-Agent`。

连接 YAML 位于 `data/config/model-connections/<uuid>.yaml`，实际 secret 位于 `data/config/agent-shell.env` 的 `AGENT_SHELL_MODEL_<UUID_WITHOUT_HYPHENS>_API_KEY`；API response 返回 `credential.status` 为 `masked`、`missing` 或 `none`，其中 `none` 表示该连接不使用凭据、`missing` 表示引用存在但环境值缺失。编辑时 `credential: null` 在 Provider 与 `base_url` 保持不变时保留原 Key；`google_vertexai` 使用无 credential 配置。名称去除首尾空白后须为 1-120 个字符且在实例内大小写不敏感唯一；格式错误返回 422 `model_connection_invalid`，重名返回 409 `model_connection_name_conflict`。

## Model Mapping

在【模型 / 模型映射】(`/models/mapping`)中查看当前 Configuration Repository 的全部模型要求。`GET /agent-shell/api/model-requirements` 返回 `{id,name,description,binding,connection}` 投影；通过 `PUT /agent-shell/api/model-requirements/{requirement_id}/binding` 提交 `{connection_id: string|null}`，`null` 表示解绑。导入配置后，要求默认未绑定；根据要求的 name 与 description 选择模型连接并保存。单个 Model Requirement 的绑定请求完成前，对应选择框保持禁用；页面刷新也会等待当前绑定请求结束，避免两个写请求以网络完成顺序反转用户选择。

同一个模型连接可以绑定多个模型要求。映射文件为 `data/config/model-bindings.yaml`，按 Repository UUID 分区。`binding==null` 或 `connection==null` 均显示 warning；repository validation 和运行装配返回 `model_requirement_unbound`。切换 Configuration Repository 后，模型连接列表保持不变，映射按仓库分别保存。
请求进入 `POST /compat/openai/v1/chat/completions` 时会原子捕获所用 Repository 的配置和 `ModelResourceSnapshot`（连接、YAML、env 与 bindings）。捕获完成后修改或删除连接、解除绑定或切换 Repository，只对后续请求生效。

## Agent Component 中的 Model Requirement

“代理组件 -> 模型要求”只编辑可迁移的 name 与多行 description，对应 Component type `model-requirement`（创建接口为 `POST /agent-shell/api/blocks/model-requirement`）。Main Agent 和 Subagent 引用模型要求 UUID；Provider、endpoint 和 credential 由本机模型连接维护。导出和导入配置时不会携带本机凭据，目标实例可以用自己的模型连接完成映射。
