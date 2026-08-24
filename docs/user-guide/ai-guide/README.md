# AI Workflow 编写指南

本目录用于指导 AI 或自动化程序通过 Management API 配置 Agent Shell。读者可以没有 Agent Shell、LangGraph 或 Deep Agents 使用经验。

本指南的完成目标是一个有限闭环：

```text
理解需求
  -> 读取当前实例事实
  -> 选择最小可用结构
  -> 创建 component / Agent / Workflow
  -> validation
  -> publish
  -> 真实 invocation
  -> 停止
```

OpenAPI 中的通用 JSON body 不表达每类 component 的完整领域字段。创建或修改对象前，先读取当前实例的 catalog、现有对象和 template projection。API response、当前源码 contract 和稳定测试是事实来源；示例只提供结构起点。

## 1. 先建立软件心智模型

Agent Shell 是 Workflow-first 的 LangGraph/Deep Agents 配置与运行外壳。

- **Management API `/api/*`**：创建和维护 configuration；
- **OpenAI-compatible API `/v1/*`**：运行已经 enabled 的 parent Workflow；
- **Workflow Graph**：决定 Node activation、State transition 和结束条件；
- **Main Agent**：提供一次完整 Agent loop；
- **Component**：为 Agent、Workflow Node 或 output projection 提供可复用配置；
- **Configuration Repository**：保存可迁移配置；
- **Model Connection**：保存当前实例私有的 Provider、model 和 credential；
- **Model Mapping**：把可迁移的 Model Requirement 绑定到本机 Model Connection。

一次 `/v1/chat/completions` 请求按 `model` 字段选择一个 enabled parent Workflow：

```text
OpenAI-compatible messages[]
  -> 按 parent Workflow name 捕获 configuration snapshot
  -> 创建 Lifecycle、parent Run 和 thread identity
  -> 把原始 messages[] 冻结到 Lifecycle Store
  -> 物化 Graph、Agent、Middleware 和 Python extension
  -> 执行 Workflow StateGraph
  -> 消费 LangGraph v3 event
  -> Agent Event Output / Workflow Event Output projection
  -> 返回 OpenAI-compatible response
```

客户端 `messages[]` 不会自动写入 Workflow root State。canvas Agent Node 以私有 `messages` 运行；需要为 Agent 注入动态初始提示词时，可以装配 Agent Additional Prompt（AAP）Custom Middleware。

## 2. Terminology convention

项目 keyword、API field 和 identifier 保持英文原名，普通说明使用中文。搜索 API、源码和文档时直接使用这些名称：

- Model Connection、Model Requirement、Model Mapping；
- Agent Event Output、Workflow Event Output、System Prompt；
- Filesystem、Filesystem Permissions、Skill；
- Custom Tool、Custom Middleware、Agent Additional Prompt（AAP）；
- Main Agent、Subagent、Command、Task Dispatcher；
- Lifecycle、Run、thread、invocation、checkpoint；
- Graph、Node、Edge、handle、State、Runtime、Context、Store；
- Normal Edge、Branch Edge、Dispatch Edge、Super-step、fan-out、fan-in。

## 3. 开始配置前先回答六个问题

AI 在写入配置前，先形成一个简短 design record：

1. **是否需要 LLM？** 确定性流程可以只使用 Command 和 Task Dispatcher；出现 Agent Node 时才需要 Main Agent 和模型。
2. **任务数量是否在设计时已知？** 已知 Node 直接用 Edge 连接；运行时动态数量使用 Task Dispatcher。
3. **是否需要 detached execution？** regular sequential/parallel Node、synchronous Subagent 和 Task Dispatcher worker 都在 current Run 内；independent child Run 才使用 background Run。
4. **状态放在哪里？** 轻量 control state 放 `shared_vars`，完整 Agent output 通过 `agent_invocations.result_ref` 读取，大型 artifact 使用 Store/Filesystem reference。
5. **Agent 从哪里获得初始提示词？** 静态角色说明使用 System Prompt；动态 request/task/upstream material 可以由 AAP 编排。
6. **什么条件表示完成？** 为 loop 写出业务退出条件；决定普通 leaf、End 和 background child 的收尾策略。

完整运行事实和推荐数据结构见 [Workflow 编排总则](00-workflow-orchestration-principles.md)。

## 4. 对象依赖与创建顺序

依赖通常从叶子对象指向根对象：

```text
Model Connection（实例私有，由用户建立）
        |
        +-> Model Mapping
               ^
               |
Model Requirement --------+
Agent Event Output --------+-> Main Agent ----+
optional Component --------+                  |
optional Subagent ----------------------------+-> Agent Node

Command component ------------------------------> Command Node
Task Dispatcher component ----------------------> Task Dispatcher Node
Workflow Event Output --------------------------> Workflow metadata

Node + Edge + layout ----------------------------> Graph document
Graph document ---------------------------------> Workflow validate / publish
enabled parent Workflow ------------------------> /v1/chat/completions model
```

推荐的创建顺序：

1. 检查 health、readiness、active Configuration Repository 和 catalog；
2. 列出现有配置，优先复用满足当前需求的对象；
3. 让用户建立所需 Model Connection；AI 描述模型能力要求；
4. 创建缺少的 component；
5. 需要 Agent Node 时创建 Subagent 和 Main Agent；
6. 创建 parent Workflow metadata；
7. 构造并保存 Graph draft；
8. 调用 Graph validation；
9. 完整校验通过后 publish Graph；
10. 检查 Model Mapping、API Server 和 `/v1/models`；
11. 发起一次真实 invocation；
12. 达到当前需求的可观察结果后停止。

每次 POST 后立即保存 response 中的 UUID。后续 reference 使用 UUID；Node ID 和 Edge ID 只在 current Graph document 内使用。

## 5. 选择最短学习路径

### 5.1 第一次使用

按顺序阅读：

1. [Workflow 编排总则](00-workflow-orchestration-principles.md)
2. [Management API、对象关系与事实发现](01-api-and-discovery.md)
3. [配置 Agent](02-components-and-agents.md)（Graph 含 Agent Node 时）
4. [创建 Workflow Graph](03-workflow-graph.md)
5. [Validation、publish 与真实 invocation](06-validation-and-references.md)

### 5.2 需要编写 Python

在阅读第三章 Graph contract 后，再读[编写 Python extension](04-python-extensions.md)。

### 5.3 需要 detached child Run

先完成 regular Workflow，再读[使用 background Run](05-background-runs.md)。

### 5.4 只修改已有对象

先读取目标对象 GET projection、第一章的 PUT 规则和对应领域章节。不要把 GET response 原样作为 PUT payload。

## 6. 三条最小成功路径

### 6.1 空 Graph

```text
Start -> End
```

用于验证 Workflow metadata、Graph wire、publish 和 `/v1` 入口。它不需要 Agent 或模型。

### 6.2 确定性 Workflow

```text
Start -> Command -> End
```

用于 State update、condition、routing、轮询或 background control。它不需要 Main Agent、Model Requirement、Model Connection 或 Agent Event Output。

### 6.3 单 Agent Workflow

```text
Start -> Agent -> End
```

它需要：

- 一个 Model Requirement；
- 一个 Agent Event Output；
- 一个 Main Agent；
- 用户建立的 Model Connection；
- Model Requirement 到 Model Connection 的 binding；
- 可选 System Prompt、AAP、Filesystem、Tool、Skill、Subagent 和其他 Middleware。

从最小路径开始，只有当前需求需要时再增加 Node 和 component。

## 7. AI 操作纪律

### 写入前

- 读取 `/api/catalog` 和 `/api/workflow-node-catalog`；
- 读取 active Configuration Repository；
- 列出目标类型的现有对象；
- 读取所需 Python template catalog；
- 确认用户选择或提供的 Model Connection；
- 写出 topology、State ownership 和结束条件。

### 写入时

- 使用 API 返回的 UUID；
- 按 schema 提交最小完整 payload；
- Python-backed component 从 catalog 的 `key + revision` 创建；
- layout 只保存展示位置；
- State 和 routing return value 分开设计；
- 不把 secret、完整用户消息或大型 artifact 复制到普通诊断和控制 State。

### 写入后

- 读取创建结果，确认 reference；
- 先保存 draft，再调用 Graph validation；
- 修正全部 `severity=error` issue；
- publish 后检查 `enabled=true`；
- 用 `/v1/models` 确认 Workflow name；
- 发起一次真实 invocation；
- 记录未验证的外部依赖或用户操作。

## 8. 如何处理错误

优先读取 HTTP status、structured error code、`detail`、`issues[]`、`path` 和 `owner_id`：

- `404`：引用对象或 endpoint 不存在，重新读取 catalog/列表；
- `409`：存在名称冲突、引用占用、未绑定模型或 operation identity 冲突；
- `422`：payload、Graph、package 或 assembly 不符合当前 contract；
- `5xx`：运行时、Provider、外部服务或系统资源失败，保留 request ID 并查看运行诊断。

收到错误后修改错误指出的 owner。不要通过删除必要字段、降低业务要求或新增兼容层绕过 validation。

## 9. 完成定义

一次 AI 配置任务达到以下条件即可交付：

- 用户要求的 topology 已保存；
- current Graph validation 返回 `valid=true`；
- Workflow 已按需求 publish 或明确保持 draft；
- 所有使用中的 Model Requirement 已绑定；
- Python extension dependency status 满足运行条件；
- 至少一次最接近需求的真实 invocation 得到可解释结果；
- 没有遗留 active background task，或已明确其继续运行的业务原因；
- 向用户说明新建对象、关键 UUID、模型要求、运行入口和未执行的验证。

## 10. 章节索引

1. [Workflow 编排总则](00-workflow-orchestration-principles.md)
2. [Management API、对象关系与事实发现](01-api-and-discovery.md)
3. [配置 Agent](02-components-and-agents.md)
4. [创建 Workflow Graph](03-workflow-graph.md)
5. [编写 Python extension](04-python-extensions.md)
6. [使用 background Run](05-background-runs.md)
7. [Validation、publish 与真实 invocation](06-validation-and-references.md)

仓库的 `examples/` 目录展示可复制起点。示例中的 business field、condition、prompt、model 和 path 都需要根据当前任务修改。function signature、return structure、Graph wire 和 API validation boundary 以对应章节与当前实例 response 为准。
