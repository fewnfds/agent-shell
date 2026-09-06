# 配置 Agent

创建可直接运行的Main Agent，或让Workflow Command启动独立Agent Run时读本章。Start、End和纯控制Command本身不需要模型。

完成结果是一个满足目标行为的 Main Agent，以及已经记录或完成的 Model Mapping；使用 MCP 时还包括 MCP Requirement、consumer Tool selection 与 MCP Mapping。

## 1. Main Agent assembly

当前 Main Agent 必须引用：

- 一个 Model Requirement；
- 一个 Filesystem Backend；
- 一个 Filesystem Tools；
- 一个 Agent Event Output。

仍应通过 `GET /agent-shell/api/catalog` 确认当前 required capability。

依赖关系如下：

```text
Model Requirement ----+
Filesystem Backend ---+
Filesystem Tools -----+-> Main Agent root graph
Agent Event Output ---+

Model Connection
  -> Model Mapping
  -> Model Requirement

MCP Connection
  -> MCP Mapping
  -> MCP Requirement
  -> Main Agent / Subagent ordered mcp_refs
```

Main Agent还可以引用System Prompt、Todo List、Exception Retry、Summarization、Prompt Caching、Custom Tool、Custom Middleware、MCP Requirement、Skill package、synchronous Subagent 和 Async Subagent 配置。直接请求或 Command facade 启动 Run 时物化该 Main Agent 的完整 assembly。

## 2. Model Requirement

Model Requirement 是可迁移的能力描述，不保存 Provider credential 或实例私有 model ID。

创建示例：

```http
POST /agent-shell/api/blocks/model-requirement
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

Model Connection 是当前实例私有资源。用户在【模型 / 模型连接】按 LangChain Provider contract 配置 Provider、Base URL、具体 model、请求参数和 credential。新建连接默认使用 `temperature=1`、`top_p=1`，并在 Provider 支持时使用 `presence_penalty=0` 与 `frequency_penalty=0`。

AI 可以说明模型必须满足的能力和兼容条件。不要虚构 Provider Key，不替用户选择未知收费模型，不把 credential 写入可迁移配置。

Model Connection 不进入 Configuration Bundle。credential value 是 write-only secret，普通 GET 只返回 configured、masked 或 missing 状态。

用户已经建立合适连接后提交 binding：

```http
PUT /agent-shell/api/model-requirements/<requirement UUID>/binding
```

```json
{
  "connection_id": "<model connection UUID>"
}
```

提交 `{"connection_id": null}` 会清除 binding。未绑定可以在 validation 中表现为 warning，但运行 assembly 会以 `model_requirement_unbound` 失败。

管理台的 Model Mapping 选择先保留在页面草稿中，用户点击右下角【确定】后写入 binding；API 调用继续通过上述 `PUT` 直接提交。

Provider-specific field 以当前 Model Connection UI、API response 和 backend validation 为准。

## 4. Agent Event Output

Agent Event Output 决定 Agent event 如何过滤和渲染为公开字符串。

先读取：

```text
GET /agent-shell/api/python-package-templates/agent-event-output
```

从 response 选择当前 template 的精确 `key` 和 `revision`，再创建 Component：

```http
POST /agent-shell/api/blocks/agent-event-output
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
POST /agent-shell/api/main-agents
```

```json
{
  "name": "Primary worker",
  "is_model_entry": false,
  "durability": "async",
  "on_disconnect": "cancel",
  "checkpoint_mode": "enabled",
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
  "mcp_refs": [],
  "subagents": [],
  "async_subagents": []
}
```

`tool_refs`、`middleware_refs`、`mcp_refs`、`subagents`和`async_subagents`分别保存 Custom Tool、Custom Middleware、MCP Requirement、direct synchronous Subagent 和 Async Subagent 配置的有序引用。每条 MCP 引用选择服务器全部 Tool 或一组原始 Tool name；创建 Connection、binding 与 secret 的步骤见 [MCP 连接、映射与调用](../mcp.md)。

`is_model_entry=true` 时，Main Agent name 直接成为 OpenAI-compatible model。`checkpoint_mode=enabled`为每个直接会话建立可复用 Thread，后续交互在同一 Thread 创建新 Run 并延续 AgentState；`disabled`使用官方 Stateless Run。`durability`在界面显示为【checkpoint 保存时机】，控制官方 Run 的 checkpoint 写入时机。`on_disconnect`在界面显示为【用户断开】；每个 Main Agent Run 创建时都冻结该值，不限于请求入口。

创建后保存Main Agent UUID。直接运行与Command-launched Run都复用这份装配；Workflow Graph不重复保存模型、Tool或prompt配置。

### Async Subagent 配置与引用

先通过`POST /agent-shell/api/async-subagents`创建可复用配置资源：

```json
{
  "component_name": "Background research",
  "main_agent_id": "<template Main Agent UUID>",
  "name": "researcher",
  "description": "Research long-running questions in the background."
}
```

再让父 Main Agent 只保存配置 UUID：

```json
{
  "async_subagents": [
    {"async_subagent_id": "<Async Subagent UUID>"}
  ]
}
```

`component_name`是配置库身份，`name`是模型可见的代理角色名并匹配`^[A-Za-z_][A-Za-z0-9_-]*$`。模板是当前 Repository 中已有的 Main Agent，不需要`is_model_entry=true`。同一个配置不能重复引用；同一父 Main Agent 的有效角色名按大小写不敏感语义唯一，模板指回父 Main Agent 时会被拒绝。

引用不会自行开启能力。父 Main Agent 还必须在`capability_refs`中显式选择`type=async-subagent`的【Async Subagent Middleware / 异步子代理中间件】组件；没有选择时引用只作为候选配置保存，不装配五个工具。组件可以设置 Middleware system prompt，并分别覆盖五个官方 Tool description；选择组件但没有有效引用时保存失败。

Deep Agents 官方`AsyncSubAgentMiddleware`提供五个工具：`start_async_task`、`check_async_task`、`update_async_task`、`cancel_async_task`和`list_async_tasks`。Launch 创建独立 child Thread/Run 并立即返回 task ID；Update 在同一 child Thread 创建新 Run。父 Agent 的`async_tasks` channel 保存 task reference，所以 checkpoint enabled 父 Thread 的后续 Run 能继续管理任务；checkpoint disabled 父 Run 结束后不保留 reference。

Async child 自己不携带 Shell Lifecycle metadata；Shell 通过父 ToolRuntime 与官方 Command 返回的 child identity 建立最小 relation。child Run 创建时冻结模板 Main Agent 的【用户断开】策略，Thread checkpoint 固定启用，checkpoint 保存时机固定为官方默认`async`，并进入父 Lifecycle 的 monitoring 与 retention。其原始 stream 不进入父 Lifecycle response；父 Agent 显式 check 并把结果写入回复后，内容才经父 Agent Event Output 公开。

本地并发容量按`1个父Run + active async child数量`计算`n_jobs_per_worker`；槽位不足时官方Run会排队。

## 6. System Prompt 和 AAP

System Prompt 适合保存每次 Agent invocation 都适用的稳定角色、长期约束和固定输出约定。

```http
POST /agent-shell/api/blocks/system-prompt
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

current request、显式Store artifact或运行时文件属于动态材料。需要这些材料时使用AAP或其他明确的Custom Middleware，不把它们硬编码进System Prompt，也不读取Workflow State中的Agent副本。

AAP 是可选 Custom Middleware template。先读取：

```text
GET /agent-shell/api/python-package-templates/middleware
```

按精确 `key == "内置示例-agent-additional-prompt"` 选择当前 revision，然后创建：

```http
POST /agent-shell/api/blocks/custom-middleware
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

AAP可以读取request `messages[]`、有明确namespace的Runtime Store artifact和Agent Filesystem。它使用private checkpointed marker，只在stateful Thread第一次执行时注入；同一Thread后续Run延续AgentState而不重复附加。每份AAP为目标Agent定义材料范围、裁剪、排序和role编排，并保留输入消息的`system`、`user`、`assistant`语义。

多个 Middleware 的顺序具有运行意义。LangChain `before_*` hook 正序执行，`after_*` hook 逆序执行，`wrap_*` 按列表嵌套。多个 Middleware 修改 `messages` 时，先明确组合顺序，再保存 `middleware_refs`。

详细 contract 见[Agent Additional Prompt](../agent-additional-prompt.md)。

## 7. 能力入口

System Prompt：保存适用于每次 invocation 的稳定角色和固定规则。

AAP或Custom Middleware：根据current request、Agent State、Store或Filesystem构造动态输入，或者在Agent lifecycle、model call、Tool call hook中运行代码。

Custom Tool：向 model-tool loop 提供由模型选择和调用的能力。

Skill：通过 CompositeBackend 的只读 `/skills/` route 提供领域知识或操作说明。

CompositeBackend：提供 mapped route、initial file、来源权限和 Skill 独立包。

LocalShellBackend：提供一个真实固定 workspace，并可与 Filesystem Tools 一起暴露 `execute`。

Filesystem Tools：控制文件 Tool visibility、description 和执行参数；该配置与 Backend 都是 required capability。

Todo List：向 Agent 提供 `write_todos` 与对应规划提示。

synchronous Subagent：Main Agent 通过 `task` Tool 同步委派给 specialist，并在取得结果后继续 Agent loop。

Async Subagent：Main Agent 通过五个官方 async task 工具启动和管理独立 Main Agent Thread/Run。

Summarization：在 Agent loop 中按配置管理 context summary。

Exception Retry：按配置处理可重试 Provider 或 Tool error。

Prompt Caching：为支持该能力的 Provider 和 model 配置显式 caching 参数。

required flag、inheritance 和 override policy 以 `/agent-shell/api/catalog` 为准。详细字段见[代理组件](../capabilities.md)。

## 8. Filesystem

Main Agent 必须分别选择 Filesystem Backend 与 Filesystem Tools。先创建 Backend：

```http
POST /agent-shell/api/blocks/filesystem
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
POST /agent-shell/api/blocks/filesystem-tools
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

Main Agent 和 synchronous Subagent 共享 current Run 的 Deep Agents StateBackend 文件状态，但可以分别继承或替换 Backend 与 Tools。跨 Workflow 调用创建的独立 Run 不自动复制该 StateBackend `files` channel。

路径、来源权限和 Skill package 见[Filesystem Backend](../../wizard-pages/filesystem-config.md)，工具字段见[Filesystem Tools](../../wizard-pages/filesystem-tools-config.md)。

## 9. Custom Tool、Custom Middleware、MCP 和 Skill

每个 `tool_refs` item 引用一个独立 Custom Tool package。Main Agent 和 Subagent 分别维护自己的 ordered Tool list。

每个 `middleware_refs` item 引用一个独立 Custom Middleware package。顺序必须与预期 hook composition 一致。

每个 `mcp_refs` item 引用一个 Repository-owned MCP Requirement，并独立保存 `all|include` Tool selection。它不引用实例 Connection UUID；Requirement 通过 MCP Mapping 绑定本机 Connection。MCP Server 公布的 Tool 已由 LangChain adapter 转为标准 `BaseTool`，不需要再创建 Custom Tool package。

创建 Skill Component 时，先读取 `GET /agent-shell/api/skills`，再提交当前实例存在的 template path：

```http
POST /agent-shell/api/blocks/skill
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
POST /agent-shell/api/subagents
```

```json
{
  "component_name": "Research specialist",
  "name": "researcher",
  "description": "Researches the delegated question and returns concise evidence with sources.",
  "settings": {
    "capability_overrides": [],
    "tool_refs": [],
    "middleware_refs": [],
    "mcp_refs": []
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

Custom Tool、Custom Middleware 和 MCP Requirement 由 Subagent 自己的 ordered `settings.tool_refs`、`settings.middleware_refs` 和 `settings.mcp_refs` 装配。

当前支持 Main Agent 的一层直接 Subagent，不接受嵌套 Subagent tree。

## 11. 本章完成结果

进入 Graph 构建前确认：

- Main Agent能够作为root graph直接运行，或由目标Command通过UUID启动；
- Model Requirement 描述能力，不包含实例 credential；
- Agent Event Output 来自当前 template `key + revision`；
- Main Agent 引用了当前 Catalog 要求的全部 required capability；
- 用户建立的 Model Connection 已记录；
- Model Mapping 已完成，或明确列为运行前用户操作；
- 目标 Agent/Subagent 使用 MCP 时，MCP Requirement、Tool selection 与 Mapping 已完成，或明确列为运行前用户操作；
- System Prompt 只保存稳定角色和规则；
- 动态 request、task 和 upstream material 有明确输入入口；
- Tool、Middleware、MCP 和 Subagent reference 已保存在目标 Agent，Skill 独立包由 CompositeBackend 引用；
- 所有 Configuration reference 使用 API 返回的 UUID。

创建或修改 Custom Tool、Custom Middleware 时继续阅读[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。随后阅读[构建 Workflow Graph](05-build-workflow-graph.md)。
