# AI Workflow 编写指南

本目录汇总 AI 或自动化程序通过 Management API 配置 Agent Shell 时所需的入口。
OpenAPI 中的通用 JSON body 不表达各 component 的完整字段；当前事实来自 API 响应、稳定测试和根 `README.md`。

## Terminology convention

本目录中的项目 keyword 使用源码、API field 和正式 contract 的英文原名，普通说明仍使用中文。不要翻译 keyword，也不要把一个
keyword 拆成中英混合词组。搜索源码时直接使用英文原名或 identifier，例如 `system prompt` 和 `system_prompt`。

固定使用以下 terminology：

- Model Connection、Model Requirement、Agent Event Output、system prompt、Filesystem、Filesystem Permissions；
- Custom Tool、Custom Middleware、Workflow Input Context（WIC）、Workflow Event Output；
- Main Agent、Subagent、Task Dispatcher；
- Lifecycle、Run、thread、invocation、checkpoint；
- Graph、Node、Edge、handle、State、Runtime、Context、Store。

## 软件如何完成一次 Lifecycle 请求

Agent Shell 是 Workflow-first 的 LangGraph/Deep Agents 配置与运行外壳。AI 可以调用 Management API 创建 component、Agent 和 Workflow；
用户通过 `POST /v1/chat/completions` 传入初始 `messages[]`，请求的 `model` 是 parent Workflow name。

```text
OpenAI-compatible messages[]
  -> 按 parent Workflow name 捕获一次 configuration snapshot
  -> 创建 Lifecycle、Run 和 thread identity，并冻结原始 messages[]
  -> 物化 Command、Task Dispatcher、Main Agent、Subagent 和 Middleware
  -> 编译并执行 Workflow StateGraph，期间 parent Workflow Run 允许创建 child Workflow Run，并归入同一 Lifecycle
  -> 消费 LangGraph stream events v3
  -> Agent Event Output / Workflow Event Output projection
  -> output assembler 按 event order 把 event string 组成一次响应
```

### Agent input 与 context

客户端 `messages[]` 只作为本次 Lifecycle 的 immutable input 保存，不自动写入 Workflow root State，也不跨请求累积成 chat history。
每个 Agent Node 启动时，都必须装配由内置 `workflow-input-context` template 创建的 Custom Middleware。
`before_agent`/`abefore_agent` hook 可以从 Runtime Store、Agent Node private State、Task Dispatcher task、earlier invocation、Filesystem 或其他可访问资源中选择材料，并构造该 Agent 独有的标准 multi-turn `messages[]`。
不同 Agent 不会自动共享 request messages 或 earlier messages；WIC 每次重新构造 context，可以通过变量和业务逻辑生成动态内容。

### Workflow 执行主线

Start 激活第一个 Work Node；
Agent Node 运行完整 Main Agent，
Command Node 可发起 child Run，并返回 State update 和 branch key，
Task Dispatcher 返回 State update 和通过 `Send` dispatch 的 tasks。
Node 的 return value 驱动 Workflow State 和 successor routing。
Agent 完成后，完整 reduced messages 写入 Lifecycle Store，
Workflow State 的 `agent_invocations` 只保存可供 successor 读取的 identity 和 result reference。
End 或没有 successor 的 reachable leaf 结束当前 path。

### Output event projection

runner 使用 LangGraph `astream_events(version="v3")` 观察 Workflow、Agent、Model、Tool 和用户 Python 产生的 event。event 不会
自动改写 Workflow State：

- Agent Node 内的 event 按来源归属该 Main Agent，由它的 Agent Event Output projection；
- Workflow-owned event 由 Workflow 可选绑定的 Workflow Event Output projection；
- Command/Task Dispatcher 可在 Runtime 中用 `get_stream_writer()` 主动写出 `custom` event；
- 每个启用的 `output(event)` 返回一个 string，runner 按 event order 组成响应；未启用或返回空 string 的 event 不输出。

Node 的 State/routing return value 与 output event 是两条独立 channel。output event 只用于单向展示，不向产生 event 的 Node 返回处理结果。具体 Python
用法见[编写 Python extension](04-python-extensions.md)，event field 见[Agent Event Output](../../wizard-pages/agent-event-output-config.md)和
[Workflow Event Output](../../wizard-pages/workflow-event-output-config.md)。

## 最小 Graph 事实

Graph 有唯一 Start 和唯一 End。下面两种结构都合法：

```text
Start -> Work Nodes（没有 outgoing Edge，自然结束）

Start -> Work Nodes -> End（显式 End，激活 End 代表这条路径结束，而不是 Graph 结束）
```

在下一个 Super-step 不再有任何 Node 可以行动，Graph 结束。
Start 不遵循隐式汇聚，强制激活与之相连的 Nodes 一次，作为开始。
End 不遵循隐式汇聚。
Work Node 可以是当前 Node catalog 允许的任意 Work Node。可达 Work Node 没有 outgoing Edge 时，路径自然结束。
一般 Workflow 可按业务放入实际需要的 Work Node，condition 和 successor selection 由 Command Node 表达。
包含 loop 的 Graph，需要明确 exit condition 的 path 使用显式 End。
Model Requirement、Agent Event Output、Main Agent 和 Workflow Input Context（WIC）Middleware 只在使用 Agent Node 时出现。
客户端 `messages[]` 不会自动写入 Workflow root State；不同配置的 WIC 负责为不同 Agent 单独构造 Agent context。

## Component 建议

向用户建议自行创建所需 Model Connection、Model Requirement、Filesystem，并指明它们的 reference relationship。

## 文档索引

阅读第一章了解 API，再按实际需求选择章节：

1. [Management API authentication、对象关系与事实发现](01-api-and-discovery.md)
2. [配置 Agent](02-components-and-agents.md)
3. [创建 Workflow Graph](03-workflow-graph.md)
4. [编写 Python extension](04-python-extensions.md)
5. [使用 background Run](05-background-runs.md)（仅使用 background task 时阅读）
6. [Validation、enabled 与真实 invocation](06-validation-and-references.md)

修改已有对象时，第一章提供 PUT 和事实发现规则，目标对象所在章节提供 domain field。
Python extension directory、dependency 与直接维护文件的规则集中在第四章；其他章节的代码片段不是完整 package contract。

本文只描述当前 Happy Path。示例中的 function signature、return structure、Graph wire、business field 和 condition rule 都只是示例。
`examples/` 只展示示例场景，按当前业务修改 code 和 import。
