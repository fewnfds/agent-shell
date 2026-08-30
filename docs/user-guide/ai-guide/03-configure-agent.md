# 配置 Agent

只有 Workflow Graph 包含 Agent Node 时才读本章。Command、Start 和 End 不需要 Main Agent 或模型。

完成结果是一个满足目标行为的 Main Agent，以及已经记录或完成的 Model Mapping。

## 1. Main Agent assembly

当前 Main Agent 必须引用：

- 一个 Model Requirement；
- 一个 Filesystem Backend；
- 一个 Filesystem Tools；
- 一个 Agent Event Output。

仍应通过 `GET /api/catalog` 确认当前 required capability。

依赖关系如下：

```text
Model Requirement ----+
Filesystem Backend ---+
Filesystem Tools -----+-> Main Agent -> Agent Node
Agent Event Output ---+

Model Connection
  -> Model Mapping
  -> Model Requirement
```

Main Agent 还可以引用 System Prompt、Todo List、Exception Retry、Summarization、Prompt Caching、Custom Tool、Custom Middleware、Skill package 和 Subagent。Agent Node 每次执行时物化该 Main Agent 的完整 assembly。

## 2. Model Requirement

Model Requirement 是可迁移的能力描述，不保存 Provider credential 或实例私有 model ID。

创建示例：

```http
POST /api/blocks/model-requirement
```

```json
{
  "name": "Tool-capable language model",
  "description": "Requires reliable tool calling and a context window suitable for the supplied task material."
}
```

description 只写真实能力要求，例如：

- 是否需要 tool calling；
- 是否需要 structured output；
- 是否需要 multimodal input；
- 预期 context 规模；
- 速度、成本或推理能力倾向。

多个 Agent 可以引用同一个或不同的 Model Requirement。每份 Requirement 描述引用它的 Agent 所需模型能力，并通过各自的 Model Mapping 绑定当前实例连接。

## 3. Model Connection 和 Model Mapping

Model Connection 是当前实例私有资源。用户在【模型 / 模型连接】按 LangChain Provider contract 配置 Provider、Base URL、具体 model、请求参数和 credential。

AI 可以说明模型必须满足的能力和兼容条件。不要虚构 Provider Key，不替用户选择未知收费模型，不把 credential 写入可迁移配置。

Model Connection 不进入 Configuration Bundle。credential value 是 write-only secret，普通 GET 只返回 configured、masked 或 missing 状态。

用户已经建立合适连接后提交 binding：

```http
PUT /api/model-requirements/<requirement UUID>/binding
```

```json
{
  "connection_id": "<model connection UUID>"
}
```

提交 `{"connection_id": null}` 会清除 binding。未绑定可以在 validation 中表现为 warning，但运行 assembly 会以 `model_requirement_unbound` 失败。

Provider-specific field 以当前 Model Connection UI、API response 和 backend validation 为准。

## 4. Agent Event Output

Agent Event Output 决定 Agent event 如何过滤和渲染为公开字符串。

先读取：

```text
GET /api/python-package-templates/agent-event-output
```

从 response 选择当前 template 的精确 `key` 和 `revision`，再创建 Component：

```http
POST /api/blocks/agent-event-output
```

```json
{
  "name": "Primary agent output",
  "python_package": {
    "folder": ""
  },
  "python_package_template": {
    "key": "<catalog key>",
    "revision": "<catalog revision>"
  }
}
```

服务端会生成该 configuration UUID 独占的 package。只需要 Assistant text 时，`output(event, origin)` 读取 `messages` payload 的 `content-block-delta` 与其中的 `delta.text`（或 `delta.reasoning`），其他 channel 或 payload 返回空字符串；流式与非流式消息都按 LangGraph v3 原始 envelope 处理。

创建和自定义 Python package 的完整流程见[编写 Python extension](06-python-extensions.md)。字段说明见[Agent Event Output](../../wizard-pages/agent-event-output-config.md)。

## 5. 创建 Main Agent

保存 Model Requirement、Filesystem Backend、Filesystem Tools 和 Agent Event Output 的 UUID，然后创建 Main Agent：

```http
POST /api/main-agents
```

```json
{
  "name": "Primary worker",
  "capability_refs": [
    {
      "type": "model-requirement",
      "block_id": "<model requirement UUID>"
    },
    {
      "type": "filesystem",
      "block_id": "<filesystem backend UUID>"
    },
    {
      "type": "filesystem-tools",
      "block_id": "<filesystem tools UUID>"
    },
    {
      "type": "agent-event-output",
      "block_id": "<agent-event-output UUID>"
    }
  ],
  "tool_refs": [],
  "middleware_refs": [],
  "subagents": []
}
```

`tool_refs`、`middleware_refs` 和 `subagents` 分别保存 Custom Tool、Custom Middleware 和 direct Subagent 的有序引用。

创建后保存 Main Agent UUID。Agent Node 只引用这个 UUID，不在 Graph Node 内重复保存模型、Tool 或 prompt 配置。

## 6. System Prompt 和 AAP

System Prompt 适合保存每次 Agent invocation 都适用的稳定角色、长期约束和固定输出约定。

```http
POST /api/blocks/system-prompt
```

```json
{
  "name": "Review agent role",
  "system_prompt": "Review the supplied material and return a concise evidence-based result."
}
```

保存 UUID，再把以下 reference 加入 Main Agent 的 `capability_refs`：

```json
{
  "type": "system-prompt",
  "block_id": "<system prompt UUID>"
}
```

当前 request、Command dispatch task、Workflow State snapshot、上游 Agent result 或运行时文件属于动态材料。需要这些材料时使用 AAP 或其他明确的 Custom Middleware，不把它们硬编码进 System Prompt。

AAP 是可选 Custom Middleware template。先读取：

```text
GET /api/python-package-templates/middleware
```

按精确 `key == "内置示例-agent-additional-prompt"` 选择当前 revision，然后创建：

```http
POST /api/blocks/custom-middleware
```

```json
{
  "name": "Primary agent additional prompt",
  "python_package": {
    "folder": ""
  },
  "python_package_template": {
    "key": "内置示例-agent-additional-prompt",
    "revision": "<catalog revision>"
  }
}
```

把以下 reference 加入 Main Agent 的 `middleware_refs`：

```json
{
  "middleware_id": "<AAP UUID>"
}
```

AAP 可以读取 request `messages[]`、`workflow_task`、`workflow_state_snapshot`、upstream invocation、Runtime Store 和 Agent Filesystem。每份 AAP 为目标 Agent 定义材料范围、裁剪、排序和 role 编排，并保留输入消息的 `system`、`user`、`assistant` role 语义。

多个 Middleware 的顺序具有运行意义。LangChain `before_*` hook 正序执行，`after_*` hook 逆序执行，`wrap_*` 按列表嵌套。多个 Middleware 修改 `messages` 时，先明确组合顺序，再保存 `middleware_refs`。

详细 contract 见[Agent Additional Prompt](../agent-additional-prompt.md)。

## 7. 能力入口

System Prompt：保存适用于每次 invocation 的稳定角色和固定规则。

AAP 或 Custom Middleware：根据当前 request、task、State 或 Store 构造动态输入，或者在 Agent lifecycle、model call、Tool call hook 中运行代码。

Custom Tool：向 model-tool loop 提供由模型选择和调用的能力。

Skill：通过 CompositeBackend 的只读 `/skills/` route 提供领域知识或操作说明。

CompositeBackend：提供 mapped route、initial file、来源权限和 Skill 独立包。

LocalShellBackend：提供一个真实固定 workspace，并可与 Filesystem Tools 一起暴露 `execute`。

Filesystem Tools：控制文件 Tool visibility、description 和执行参数；该配置与 Backend 都是 required capability。

Todo List：向 Agent 提供 `write_todos` 与对应规划提示。

Subagent：Main Agent 通过 `task` Tool 同步委派给 specialist，并在取得结果后继续 Agent loop。

Summarization：在 Agent loop 中按配置管理 context summary。

Exception Retry：按配置处理可重试 Provider 或 Tool error。

Prompt Caching：为支持该能力的 Provider 和 model 配置显式 caching 参数。

required flag、inheritance 和 override policy 以 `/api/catalog` 为准。详细字段见[代理组件](../capabilities.md)。

## 8. Filesystem

Main Agent 必须分别选择 Filesystem Backend 与 Filesystem Tools。先创建 Backend：

```http
POST /api/blocks/filesystem
```

```json
{
  "name": "AI workflow filesystem",
  "backend_type": "composite",
  "mapped_directories": [
    {
      "virtual_path": "/workspace/",
      "local_path": "H:\\projects\\my-app",
      "path_origin": "absolute",
      "lifecycle_mode": "fixed",
      "permission": "read-write"
    }
  ],
  "skill_package_id": null
}
```

再创建 Tools：

```http
POST /api/blocks/filesystem-tools
```

```json
{
  "name": "AI workflow filesystem tools",
  "tool_configs": {
    "read_file": {"visible": true},
    "execute": {"visible": false}
  }
}
```

保存两个 response UUID，并分别作为 Main Agent 的 `filesystem` 与 `filesystem-tools` capability reference。需要执行命令时把 Backend 改为 `backend_type=local-shell`，只提交一个现有 `workspace`，并把 Tools 的 `execute.visible` 设为 `true`。CompositeBackend 会自动隐藏 execute。

Main Agent 和 synchronous Subagent 共享 current Run 的 Deep Agents StateBackend 文件状态，但可以分别继承或替换 Backend 与 Tools。独立 background Run 不自动复制该 StateBackend `files` channel。

路径、来源权限和 Skill package 见[Filesystem Backend](../../wizard-pages/filesystem-config.md)，工具字段见[Filesystem Tools](../../wizard-pages/filesystem-tools-config.md)。

## 9. Custom Tool、Custom Middleware 和 Skill

每个 `tool_refs` item 引用一个独立 Custom Tool package。Main Agent 和 Subagent 分别维护自己的 ordered Tool list。

每个 `middleware_refs` item 引用一个独立 Custom Middleware package。顺序必须与预期 hook composition 一致。

创建 Skill Component 时，先读取 `GET /api/skills`，再提交当前实例存在的 template path：

```http
POST /api/blocks/skill
```

```json
{
  "name": "Writing skills",
  "skill_template_paths": [
    "writing/outline",
    "review/continuity-check"
  ]
}
```

后端把所选 Skill Template 复制到该 Component 的 Skill 独立包，之后 Template 与 Component 独立。独立包内的 Skill 名称必须唯一。Skill Component 不直接装配到 Agent；保存后把它的 UUID 写入 CompositeBackend 的 `skill_package_id`。

Custom Tool、Custom Middleware 与 hook 见[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。通用 Python package contract 见[编写 Python extension](06-python-extensions.md)。Skill 见[Skill 配置](../../wizard-pages/skill-config.md)。

## 10. Subagent

Subagent 用于 Main Agent 内部的一层 synchronous delegation。

创建示例：

```http
POST /api/subagents
```

```json
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

保存 UUID，再把以下 reference 加入 Main Agent 的 `subagents`：

```json
{
  "subagent_id": "<Subagent UUID>"
}
```

`name` 是模型可见的 task route。`description` 明确说明何时委派、负责什么和返回什么。

Subagent 默认继承 Main Agent 的 inheritable capability。需要不同 Model Requirement、System Prompt、Filesystem Backend 或 Filesystem Tools 时使用 capability override。required Model Requirement、Filesystem Backend 与 Filesystem Tools 不能 disabled；Skill package 随 CompositeBackend 一起继承或替换。

Custom Tool 和 Custom Middleware 由 Subagent 自己的 ordered `settings.tool_refs` 和 `settings.middleware_refs` 装配。

当前支持 Main Agent 的一层直接 Subagent，不接受嵌套 Subagent tree。

## 11. 本章完成结果

进入 Graph 构建前确认：

- Agent Node 引用了目标 Main Agent UUID；
- Model Requirement 描述能力，不包含实例 credential；
- Agent Event Output 来自当前 template `key + revision`；
- Main Agent 引用了当前 Catalog 要求的全部 required capability；
- 用户建立的 Model Connection 已记录；
- Model Mapping 已完成，或明确列为运行前用户操作；
- System Prompt 只保存稳定角色和规则；
- 动态 request、task 和 upstream material 有明确输入入口；
- Tool、Middleware 和 Subagent reference 已保存在目标 Agent，Skill 独立包由 CompositeBackend 引用；
- 所有 Configuration reference 使用 API 返回的 UUID。

创建或修改 Custom Tool、Custom Middleware 时继续阅读[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。随后阅读[构建 Workflow Graph](05-build-workflow-graph.md)。
