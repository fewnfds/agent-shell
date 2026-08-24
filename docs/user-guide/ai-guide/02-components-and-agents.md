# 配置 Agent

Graph 没有 Agent Node 时跳过本章。Command、Task Dispatcher、Start 和 End 不需要 Main Agent、Model Requirement 或模型。

Graph 含 Agent Node 时，先完成一个最小 Main Agent，再按业务增加可选能力。Main Agent 的 required capability 只有 Model Requirement 和 Agent Event Output。

## 1. 最小依赖链

```text
Model Requirement ----+
                      +-> Main Agent -> Agent Node
Agent Event Output ---+

Model Connection（用户在当前实例建立）
        |
        +-> Model Mapping -> Model Requirement
```

建议按以下顺序创建：

1. 创建 Model Requirement；
2. 从 template 创建 Agent Event Output；
3. 创建最小 Main Agent；
4. 让用户建立 Model Connection；
5. 把 Model Requirement 绑定到 Model Connection；
6. 把 Main Agent UUID 写入 Agent Node config；
7. 真实 invocation 成功后，再增加 System Prompt、AAP、Filesystem、Tool、Skill 或 Subagent。

## 2. Model Requirement、Model Connection 与 Model Mapping

Model Requirement 是可迁移的能力描述。它说明 Agent 需要怎样的模型，不保存 Provider credential 或实例私有 model ID。

```http
POST /api/blocks/model-requirement
Authorization: Bearer <management token>
Content-Type: application/json

{
  "name": "Tool-capable language model",
  "description": "A language model with reliable tool calling support. Prefer a moderate or larger context window."
}
```

description 应描述真实能力要求，例如 tool calling、structured output、multimodal input、context window、速度或成本倾向。多个 Agent 的要求相同时可以复用一个 Model Requirement。

Model Connection 是当前实例私有配置。用户在【模型 -> 模型连接】中按 LangChain Provider contract 填写 Provider、Base URL、具体 model、请求参数和 credential。AI 可以明确说明所需能力和兼容条件；不要虚构 Provider Key、替用户选择未知的收费模型，或把 credential 写进可迁移配置。

Model Connection 不属于 Configuration Repository，也不进入 Bundle。credential 是 management-only write-only input，实际值进入实例 env；普通 GET response 只返回 masked/missing 状态。

用户创建连接后，把 Requirement 绑定到 Connection：

```http
PUT /api/model-requirements/<requirement UUID>/binding
Authorization: Bearer <management token>
Content-Type: application/json

{"connection_id":"<model connection UUID>"}
```

提交 `{"connection_id": null}` 可以清除 binding。未绑定会在 validation 中产生 warning，运行装配时返回结构化 `model_requirement_unbound`。

Provider-specific field 以【模型 / 模型连接】和 backend validation 为准。OpenAI Model 的 `provider_settings.use_responses_api` 默认是 `false`，对应 OpenAI-compatible Chat Completions；直连 endpoint 支持 OpenAI Responses API 时可以设为 `true`。

## 3. Agent Event Output

每个 Main Agent 引用一个 `agent-event-output` component。先读取 current Template catalog：

```http
GET /api/python-package-templates/agent-event-output
Authorization: Bearer <management token>
```

从 response 选择 template 的 `key` 和 `revision`，再创建 component：

```http
POST /api/blocks/agent-event-output
Authorization: Bearer <management token>
Content-Type: application/json

{
  "name": "Primary agent output",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "<catalog key>",
    "revision": "<catalog revision>"
  }
}
```

服务端为该 component 生成独占 package directory。只需要最终 Assistant text 时，`main.py` 可以按以下方式过滤 event：

```python
def output(event):
    if event["event_type"] == "assistant_text":
        return event["message"]
    return ""
```

package 只定义一个同步 `def output(event)`。它负责 event filtering 和 string rendering；State update、routing 和业务异常处理放在各自 owner 中。完整 field 见[Agent Event Output](../../wizard-pages/agent-event-output-config.md)。

## 4. 创建最小 Main Agent

保存 Model Requirement 和 Agent Event Output 的 UUID，然后创建 Main Agent：

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
  "tool_refs": [],
  "middleware_refs": [],
  "subagents": []
}
```

`middleware_refs: []` 是合法的最小配置。`tool_refs`、`middleware_refs` 和 `subagents` 只有当前任务需要时才增加。

## 5. System Prompt 与动态 Agent 初始提示词

两类提示材料适合不同生命周期：

| 材料 | 推荐位置 | 示例 |
| --- | --- | --- |
| 稳定角色、长期约束、固定输出约定 | System Prompt component | “负责审核数据并返回 JSON” |
| 本次 request、当前 task、上游结果、运行时 context | AAP 或其他 Custom Middleware | client `messages[]`、`workflow_task.payload`、前序 `result_ref` |

创建 System Prompt component：

```http
POST /api/blocks/system-prompt
Authorization: Bearer <management token>
Content-Type: application/json

{
  "name": "Review agent role",
  "system_prompt": "Review the supplied material and return a concise evidence-based result."
}
```

保存 response UUID，再把 `{"type":"system-prompt","block_id":"<system prompt UUID>"}` 加入 Main Agent 的 `capability_refs`。没有选择 System Prompt 时，Agent assembly 使用框架默认行为。

客户端 `messages[]` 保存在 current Lifecycle Store，不会自动成为 Workflow root State。需要让 Agent 使用本次 request 或动态运行材料时，建议采用 Agent Additional Prompt（AAP）范式，在 Agent invocation 开始前选择材料并构造该 Agent 的 private `messages`。

AAP 是可选的 Custom Middleware template。读取 catalog：

```http
GET /api/python-package-templates/middleware
```

按精确 `key == "内置示例-agent-additional-prompt"` 选择当前 revision，再创建 Custom Middleware：

```json
{
  "name": "Primary agent additional prompt",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "内置示例-agent-additional-prompt",
    "revision": "<catalog revision>"
  }
}
```

提交到 `POST /api/blocks/custom-middleware`，再把 `{"middleware_id":"<AAP UUID>"}` 加入 Main Agent 的 `middleware_refs`。AAP 可以从 request `messages[]`、`workflow_task`、`workflow_state_snapshot`、upstream invocation、Runtime Store 或 Filesystem 中选择 current Agent 真正需要的材料。详细 contract 见 [Agent Additional Prompt](../agent-additional-prompt.md)。

多个 Middleware 的顺序具有运行意义：LangChain `before_*` hook 正序执行，`after_*` 逆序执行，`wrap_*` 按列表嵌套。多个 Middleware 修改 `messages` 时，先设计组合顺序，再按该顺序保存 `middleware_refs`。

## 6. 可选能力选择

| 需求 | 选择 | 判断规则 |
| --- | --- | --- |
| 固定角色说明 | System Prompt | 内容对该 Agent 的每次 invocation 都适用 |
| 动态初始提示词 | AAP / Custom Middleware | 每次需要从 request、task、State snapshot 或 Store 选择材料 |
| 调用外部或确定性能力 | Custom Tool | 能力应由模型在 Agent loop 中选择和调用 |
| 加载成组操作说明 | Skill | Agent 需要按需读取领域知识或操作流程 |
| 读写工作文件 | Filesystem | 需要持久于 Agent loop 的文件、mapped route 或更多 Filesystem Tool |
| 限制路径和 Filesystem Tool | Filesystem Permissions | 需要显式 allow/deny 或 tool visibility |
| 维护 Agent 内部任务计划 | Todo List | 任务足够复杂，需要 `write_todos` 管理计划 |
| 同步委派给专门角色 | Subagent | Main Agent 需要等待 specialist 返回结果后继续 current Agent loop |
| 模型调用或 Tool lifecycle hook | Custom Middleware | 行为属于 LangChain Agent Middleware lifecycle |
| 统一处理可重试异常 | Exception Retry | 需要 Provider-native 或 Middleware retry policy |
| 控制长 Agent context | Summarization | 长对话或 Tool loop 需要按策略摘要 |
| 使用 Provider prompt cache | Prompt Caching | 所选 Provider/model 支持并需要显式 caching 配置 |

完整 component type、required flag、inheritance 和 override policy 以 `GET /api/catalog` 为准，字段说明见[代理组件](../capabilities.md)。

### 6.1 Filesystem

不创建、不选择 Filesystem 时，Agent 使用 request-scoped empty `StateBackend`，并只暴露 `read_file` Tool。这是合法的 minimal Filesystem。

需要 mapped route、initial file 或更多 Filesystem Tool 时创建 component：

```http
POST /api/blocks/filesystem
Authorization: Bearer <management token>
Content-Type: application/json

{"name":"AI workflow filesystem"}
```

保存 response `id`，并作为 Main Agent 或 Subagent 的 `filesystem` capability reference。Subagent 默认继承 Main Agent 的选择，需要差异化时通过 `capability_overrides` 执行 `replace` 或 `disabled`。路径和权限见[Filesystem 权限配置](../../wizard-pages/filesystem-permissions-config.md)。

### 6.2 Custom Tool

每个 `tool_refs` item 引用一个独立 Custom Tool package。Main Agent 与 Subagent 分别维护 ordered Tool 列表，不通过 capability override 继承、替换或关闭。扩展的同步 `create_tool()` 返回一个 LangChain `BaseTool`，最后按引用顺序传给 Agent assembly。

### 6.3 Skill

`GET /api/skills` 返回可选择的 Skill Template。创建 Skill component 时向 `POST /api/blocks/skill` 提交名称和 template path：

```json
{
  "name": "Writing skills",
  "skill_template_paths": ["writing/outline", "review/continuity-check"]
}
```

后端把所选 Template 复制到该 component UUID 拥有的私有 package，之后两者独立。私有包内的 Skill 名称必须唯一。详细操作见[Skill 配置](../../wizard-pages/skill-config.md)。

## 7. 可选 Subagent

Subagent 用于 Agent 内部的一层同步 delegation。先创建 Subagent：

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

再把 `{"subagent_id":"<UUID>"}` 加入 Main Agent 的 `subagents`。

Subagent 默认继承 Main Agent 的 inheritable capability。需要不同 Model Requirement、System Prompt、Filesystem 或 Filesystem Permissions 时使用 override；required `model-requirement` 不能 `disabled`。Custom Tool 和 Custom Middleware 分别由 Subagent 自己的有序 `settings.tool_refs`、`settings.middleware_refs` 装配。

`name` 是 Model-visible routing name。`description` 应说明何时委派、负责什么、返回什么。当前 contract 支持 Main Agent 的一层直接 Subagent，不接受嵌套 Subagent tree。

## 8. Configuration Bundle

跨实例分享时，以一个 component、Subagent、Main Agent 或 Workflow UUID 作为 Bundle root。系统沿 typed reference 计算完整 dependency closure。导入后的 configuration UUID 会改变，Workflow-local Node/Edge ID 保持不变；Model Connection 和 credential 需要在目标实例重新建立和映射。

导出、preview、resolution、trusted-code review 和 import 流程见[管理配置库](../configuration-library.md)。导入后的 Workflow 保持 disabled，完成模型映射、Filesystem binding、Python dependency 和 validation 后再 publish。最终验收顺序见[Validation、publish 与真实 invocation](06-validation-and-references.md)。

## 9. Agent 装配完成检查

- Graph 确实需要 Agent Node；
- Model Requirement description 表达能力，不含实例 credential；
- Agent Event Output 来自 current Template `key + revision`；
- Main Agent 同时引用 Model Requirement 和 Agent Event Output；
- 用户建立的 Model Connection 已记录；
- Model Requirement binding 已完成，或明确列为用户待办；
- System Prompt 只保存稳定角色说明；
- 动态 request/task/upstream material 有明确入口，需要时采用 AAP；
- Tool、Skill、Filesystem、Middleware 和 Subagent 都有当前业务调用方；
- 所有 reference 使用 API 返回的 UUID。

下一步：[创建 Workflow Graph](03-workflow-graph.md)。
