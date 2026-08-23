# 配置 Agent

只有包含 Agent Node 时才需要 Main Agent。Main Agent 的必选 capability 仅为 Model Requirement 与 Agent Event Output；Filesystem、Workflow Input Context（WIC）Custom Middleware、Skill、Tool、Subagent 等均按需选择。没有 Agent Node 的 Graph 不需要创建 Agent 装配对象。

## Filesystem

每个 Main Agent 可选择一个 Filesystem；Subagent 默认继承 Main Agent 的选择，需要差异化时通过 `capability_overrides` 执行 `replace` 或 `disabled`。
不创建、不选择 Filesystem 时，Agent 自动使用 request-scoped 空 `StateBackend`，并只暴露 `read_file` tool；这就是最小 Filesystem。
只有需要 mapped route、initial file 或更多 Filesystem Tool 时才创建 component：

```http
POST /api/blocks/filesystem
Authorization: Bearer <management token>
Content-Type: application/json

{"name":"AI workflow filesystem"}
```

保存响应中的 `id`，并把它作为 Main Agent 或 Subagent 的 `filesystem` capability ref。可选的 `filesystem-permissions` capability 负责路径 allow/deny 与 Filesystem tool 可见性；字段见[Filesystem 权限配置](../../wizard-pages/filesystem-permissions-config.md)。

## Model Connection 与 Model Requirement

在【模型 -> 模型连接】创建实例私有 Model Connection，按 LangChain Provider contract 填写 endpoint、具体 model、请求参数和凭据。配置库与系统中的【模型连接】复用通用列表，只提供查看、编辑、复制和删除，不提供下载。连接不属于 Configuration Repository，也不会进入 Bundle；凭据实际值只写入实例 env，普通响应仅返回 masked/missing 状态。

在【代理组件 -> 模型要求】创建可迁移的模型能力要求，只填写名称和多行 description。导入配置后，在【模型 -> 模型映射】按 description 选择模型连接；未绑定只产生 warning，运行装配时返回结构化 `model_requirement_unbound`。

`credential` 是 management-only 的 write-only input。创建 Model Connection 时在 HTTPS 或本机 loopback 连接中提交真实 Provider Key；
服务端把它写入 `agent-shell.env` 的独立 environment variable，并在 Model Connection YAML 中保存 variable reference。GET 响应提供只读的 masked/missing 状态。编辑同一 Provider 与 Base URL 时，PUT 传 `credential: null` 会保留现有 Key，传新 Key 会替换凭据。

```http
POST /api/model-connections
Authorization: Bearer <management token>
Content-Type: application/json

{
  "name": "Primary local connection",
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "credential": "<write-only Provider API Key>",
  "model": "<current-model-id>",
  "provider_settings": {"use_responses_api": false},
  "tool_choice": null,
  "response_format": null,
  "model_settings": {}
}
```

Provider 和 Provider-specific field 以【模型 / 模型连接】页及 backend validation 为准。OpenAI Model 的 `provider_settings.use_responses_api` 默认是 `false`，对应 OpenAI-compatible Chat Completions；直连 endpoint 支持官方 OpenAI Responses API 时可设为 `true`。当前实例的 Model 事实来自模型连接列表。

## Skill

`GET /api/skills` 扫描 `data/skills-template/`，只返回可选择的 Skill Template。Template 可以位于多层目录中；扫描遇到第一份 `SKILL.md` 就把该目录作为完整边界，并使用返回的 `template_path` 区分不同路径下的同名 Skill。

创建 Skill Component 时向 `POST /api/blocks/skill` 提交名称和所选路径，例如：

```json
{
  "name": "Writing skills",
  "skill_template_paths": ["writing/outline", "review/continuity-check"]
}
```

后端把所选 Template 复制到该 Component UUID 拥有的私有 Skill package，之后两者独立。`GET /api/blocks/skill/{block_id}/skills` 读取私有包；`POST` 同一路径并提交 `{"template_path":"..."}` 可增加 Skill，`DELETE /api/blocks/skill/{block_id}/skills/{folder_name}` 可删除。私有包内的 Skill 名称必须唯一，同名新增返回冲突，需要先删除再添加。私有包内容问题只在组件页载入或显式刷新时作为 warning 展示，不阻塞保存、Repository 切换、Bundle 或 Agent 装配。字段和页面行为见[Skill 配置](../../wizard-pages/skill-config.md)。

## Agent Event Output

Main Agent 的 required reference 包含一个 `agent-event-output` package。先从 template catalog 选择一个合法模板：

```json
{
  "name": "Primary agent output",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "<catalog key>",
    "revision": "<catalog revision>"
  }
}
```

提交到 `POST /api/blocks/agent-event-output`。推荐先读取 `GET /api/python-package-templates/agent-event-output`，使用返回的 `key` 和 `revision`，保存后配置拥有独占 package 目录。


若只需要最终 Assistant text，可以在同一个入口中过滤其他 event：

```python
def output(event):
    if event["event_type"] == "assistant_text":
        return event["message"]
    return ""
```

`main.py` 只定义一个同步 `def output(event)`。在函数内按 `event["event_type"]` 处理全部事件，return type 为 `str`，
返回 `""` 表示过滤。完整 Agent event 及 field 见[Agent Event Output](../../wizard-pages/agent-event-output-config.md)。

## Workflow Input Context（WIC）Custom Middleware

Middleware template catalog 来自：

```http
GET /api/python-package-templates/middleware
```

在 `catalog` 中按精确 `key == "内置示例-workflow-input-context"` 选择 template。使用该项返回的 `key` 和 `revision` 创建 Custom Middleware。catalog 返回当前模板身份、文件投影和 revision，文档不复制整份 WIC source：

```json
{
  "name": "Default workflow input context",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "内置示例-workflow-input-context",
    "revision": "<catalog revision>"
  }
}
```

提交到 `POST /api/blocks/custom-middleware`。独占 package folder 由服务端生成，客户端 payload 中的 folder 初始为空。

内置 WIC 给出三项建议起点：Main Agent 读取本次 Lifecycle 的 request `messages[]`、Subagent 保留 delegated messages、Task Dispatcher worker 把自己的 private task 加入 Agent context。当前 Agent 可以在 `build_workflow_input_messages(state, runtime, request_messages, backend)` 中按职责选择 request messages、private State、parent Graph snapshot、
Task Dispatcher task、Runtime Context、Store 或当前 Agent Filesystem 材料；不需要的默认步骤可以删除。详细边界见[Workflow Input Context](../workflow-input-context.md)。

## Main Agent

最小 Main Agent 引用 Model Requirement、Agent Event Output 和 WIC：

```http
POST /api/main-agents
Authorization: Bearer <management token>
Content-Type: application/json

{
  "name": "Primary worker",
  "capability_refs": [
    {"type": "model-requirement", "block_id": "<model requirement UUID>"},
    {"type": "agent-event-output", "block_id": "<agent-event-output UUID>"}
  ],
  "tool_refs": [
    {"tool_id": "<custom-tool UUID>"}
  ],
  "middleware_refs": [
    {"middleware_id": "<WIC UUID>"}
  ],
  "subagents": []
}
```

`middleware_refs` 有顺序：LangChain 的 `before_*` hook 正序执行，`after_*` 逆序执行，`wrap_*` 按列表嵌套。
多个 Middleware 改写 `messages` 时，list order 决定组合方式。

`tool_refs` 也有顺序；每个引用对应一个独立 Custom Tool Python extension。Main Agent 与 Subagent 分别维护自己的 Tool 列表，
不会通过 capability override 继承、替换或关闭。扩展的 `create_tool()` 返回一个 LangChain `BaseTool`，最后按这个列表传给 `create_deep_agent(tools=...)`。

## 可选 Subagent

Subagent 用于 Agent 内部的同步委派和复杂任务隔离。先创建 Subagent entity：

```http
POST /api/subagents
Authorization: Bearer <management token>
Content-Type: application/json

{
  "component_name": "Research specialist",
  "name": "researcher",
  "description": "Researches the delegated question and returns concise evidence with sources.",
  "settings": {
    "capability_overrides": [],
    "tool_refs": [],
    "middleware_refs": []
  }
}
```

然后把 `{"subagent_id":"<UUID>"}` 加入 Main Agent 的 `subagents`。Subagent 默认继承 Main Agent 的 inheritable capability；不同的 Model Requirement、system prompt 或 Filesystem Permissions 通过 override 表达，但 required 的 `model-requirement` 不能 `disabled`。Custom Tool/Middleware 不走 capability override，分别通过自己的有序 `settings.tool_refs`/`middleware_refs` 装配。Main Agent 引用 `subagent` delegation capability component 后，`task` Tool description 与 routing prompt 来自当前业务配置。

Subagent 的 `name` 是 Model-visible routing name；清楚描述 delegation timing、职责和 return content 有助于 Model routing。当前 contract 只支持 Main Agent 的一层直接 Subagent，不接受嵌套 Subagent 树。

## 可移植配置 Bundle

管理台的【配置库】是单根 Bundle 下载和上传入口；Repository 切换、复制、整仓库下载和删除位于【配置库 / 全局 / 组件配置】。Management API 使用 `POST /api/configuration-bundles/export` 导出，使用 `POST /api/configuration-bundles/preview` 上传预检，再使用 `POST /api/configuration-bundles/import` 提交同一文件和预检计划；完整 multipart 字段见[管理配置库](../configuration-library.md)。这些操作以 active Configuration Repository 为读取或写入目标。

需要跨实例分享时，以一个 Component、Subagent、Main Agent 或 Workflow UUID 作为 Bundle root。后端沿 `configuration.dependencies` 的 typed references 计算 transitive closure；不要按名称猜依赖，也不要扫描或替换 Python source 中的 UUID。preview 为每个 source Configuration UUID 给出固定 target UUID，并返回名称建议、Filesystem bindings、阻塞项、warnings 和 trusted-code warnings。

导入时以 multipart 重新上传 preview 使用的同一 ZIP，并提交 `request` JSON；其中包含相同 `bundle_sha256`、`plan_token` 与完整 `resolutions`（target UUID、name 和必要的 Filesystem binding）。`filesystem_binding_required` 等阻塞项未解决时 preview 的 `ready=false`，不能提交。所有配置 UUID 都改变，Node/Edge ID 等 Workflow-local topology key 保持不变；Python package folder/manifest owner UUID 跟随 Component target UUID。Workflow 必须保持 disabled，待 credential、path、Skill、Python code 和 dependency 复核完成后再走正常 Graph validation/publish。

下一步：[创建 Workflow Graph](03-workflow-graph.md)。
