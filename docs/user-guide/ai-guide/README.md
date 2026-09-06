# AI 配置指南

本目录指导 AI 或自动化程序通过 Management API 发现、配置、运行和验证 Agent Shell。内容围绕当前实例事实、对象关系、运行语义、代码入口与可观察验收组织。

建议安装 langchain-docs mcp，查询资料提升效率，尝试列出 MCP，如果没有则提醒用户。

## 1. 事实优先级

处理配置任务时按以下顺序判断事实：

1. 当前实例的 API response、Catalog、目标对象 GET projection 和 structured validation issue；
2. 当前源码 contract 与稳定测试；
3. 本指南和其他当前状态文档；
4. 仓库中的可运行示例；
5. LangChain、LangGraph 和 Deep Agents 官方文档；
6. 模型记忆。

Catalog key、template revision、UUID、Node handle、Model/MCP Connection、Model/MCP Mapping 和当前设置必须从实例读取。不要从示例或模型记忆猜测动态值。

Agent Shell 使用 LangGraph 和 Deep Agents，但只提供已经完成产品闭环的能力。官方框架支持某项功能，不代表 Agent Shell 当前 Catalog 已经提供该功能。

【建议】用户为执行配置任务的 AI 客户端安装或连接 [LangChain Docs MCP](https://docs.langchain.com/mcp)，用它查询 LangChain、LangGraph 和 Deep Agents 的概念指南、操作说明与示例。查询结果按上述事实优先级与当前实例 Catalog、项目源码 contract 和稳定测试核对。

## 2. 产品入口

Management API 使用 `/agent-shell/api/*`，负责发现、创建、修改、校验和发布配置。

OpenAI-compatible API 使用 `/compat/openai/v1/*`，负责发现和运行 `is_model_entry=true` 的 Main Agent，以及 `enabled=true` 且 `is_model_entry=true` 的 Workflow。其他请求入口也复用同一套官方 Assistant、Thread 与 Run 执行模型。

一次外部请求按以下路径运行：

```text
OpenAI-compatible messages[]
  -> 按 model 选择 Main Agent 或 Workflow 入口
  -> 捕获当前配置与 Model/MCP 资源快照
  -> 创建或复用官方 Assistant，并创建或续接 Thread上的新 Run
  -> dynamic graph factory 从同一快照物化 Main Agent Graph 或 Workflow Graph
  -> LangGraph Dev Worker 执行对应 root Graph
  -> 对应 Agent/Workflow Event Output 投影原始 event
  -> 返回 OpenAI-compatible response
```

客户端 `messages[]` 是标准 OpenAI-compatible 多轮 `system`、`user`、`assistant` 消息。Main Agent入口把它们作为官方Run input写入AgentState；同一stateful Thread上的后续Run延续该State。Workflow入口把输入保存在Lifecycle Store快照中，Workflow State只保存`shared_vars`。跨Thread共享的业务材料使用有明确namespace、writer和reader的Store artifact或Filesystem reference。

需要在Thread第一次执行时整理Agent输入时，为该Agent装配Agent Additional Prompt（AAP）或其他明确的Custom Middleware。AAP从current AgentState messages或显式Store/Filesystem来源选择材料，并用private checkpoint marker保证同一stateful Thread只初始化一次。

## 3. 配置对象关系

常见依赖方向如下：

```text
Component
  -> Subagent
  -> Main Agent

Component
  -> Workflow metadata / Command
  -> Workflow control Graph

Main Agent is_model_entry | enabled Workflow is_model_entry
  -> /compat/openai/v1/chat/completions
```

Model Connection 是当前实例私有资源。Model Requirement 是可迁移的能力描述。Model Mapping 把当前 Configuration Repository 中的 Model Requirement 绑定到本机 Model Connection。

MCP Connection 也是当前实例私有资源。Repository-owned MCP Requirement 保存稳定 namespace，MCP Mapping 把它绑定到本机 MCP Connection；Main Agent、Subagent 和 Command 再通过各自的 ordered `mcp_refs` 选择可用 Tool。

Workflow Graph 决定 Command super-step、State transition 和结束条件。Main Agent 表示一次完整 Deep Agents Agent loop，并可通过 ordered AsyncSubAgent references 启动独立后台 Thread/Run。Component 为 Agent、Command 或 output projection 提供配置。

## 4. 开始前形成任务记录

写入配置前，先用简短文本回答：

1. 用户需要的可观察结果是什么；
2. 哪些步骤需要模型推理，哪些步骤是确定性逻辑；
3. Node 数量是否在设计时已知；
4. 是否启动另一个独立 Workflow Run，以及 caller/spawned Run 的 State、cancellation 和 result handoff；
5. 每类运行数据由哪个 State、Store 或 Filesystem owner 保存；
6. 每个 Agent 从哪里获得初始工作材料；
7. 正常成功、业务失败和循环退出分别由什么条件表示。

暂时未知的 UUID、Catalog key 或 template revision 不写成假值。在 discovery 阶段读取后再加入 reference ledger。

## 5. 标准操作闭环

每次配置任务按以下有限流程进行：

```text
理解需求
  -> 发现当前实例事实
  -> 设计 Workflow topology、运行机制和数据 owner
  -> 读取、创建或引用任务使用的配置
  -> 保存 Graph draft
  -> 验证同一份完整 Graph document
  -> publish
  -> 检查 Model/MCP Mapping 和 Python dependency
  -> 确认 /compat/openai/v1/models
  -> 发起与任务相符的真实 invocation
  -> 交付验收结果
```

创建或更新对象后保存 API 返回的 UUID。Configuration reference 使用 UUID。Node ID 和 Edge ID 只在当前 Graph document 内使用。

记录整个 Repository 的既有 warning；本次任务负责其创建或修改对象以及目标运行路径中的问题。

## 6. 阅读路径

所有任务先读[发现当前实例事实](01-discover-current-instance.md)，再读[设计 Workflow](02-design-workflow.md)。

如果任务需要Main Agent，再读[配置Agent](03-configure-agent.md)。纯Command Workflow可以跳过Agent章节。

创建或修改 Custom Tool、Custom Middleware 时读[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。

所有 Workflow 都需要读[构建 Workflow Graph](05-build-workflow-graph.md)。

创建或修改 Command、Agent Event Output、Workflow Event Output 或其他 Python-backed component 时读[编写 Python extension](06-python-extensions.md)。该章同时说明五类 Python package 共用的文件与 dependency contract。

需要从 current Workflow Run 启动另一个独立 Main Agent或Workflow Run时读[跨 Workflow Run 调用](07-cross-workflow-runs.md)。Main Agent使用官方AsyncSubAgent时同时阅读[配置Agent](03-configure-agent.md)中的异步委派边界。

所有任务最后读[验证、运行与交付](08-validate-run-deliver.md)。

## 7. 写入纪律

写入前：

- 确认 base URL、credential domain、认证 credential 是否可由本地程序或运行平台取得，以及 active Configuration Repository；
- 按[发现当前实例事实](01-discover-current-instance.md)的认证边界使用 `AGENT_SHELL_MANAGEMENT_TOKEN` 和 `AGENT_SHELL_API_KEY`；操作 Agent 不打开或接收实例 secret store 的内容，不要求用户在对话中发送 secret；
- 读取 `/agent-shell/api/catalog`、`/agent-shell/api/workflow-node-catalog` 和 `/agent-shell/api/configuration-options`；
- 读取准备复用或修改的完整对象；
- 读取需要使用的 Python template catalog；
- 明确 topology、State ownership、Agent input 和结束条件。

写入时：

- 按当前 endpoint contract 提交可写 payload；
- 修改现有对象时保留未修改的必需可写字段；
- 不把 GET response、masked secret 或 collection envelope 原样作为 PUT payload；
- Python-backed component 使用当前 catalog 返回的 `key + revision`；
- Graph layout 只保存展示位置；
- 不把 secret、完整用户消息或大型 artifact 复制到普通控制 State 或诊断摘要。

写入后：

- GET 回读创建或修改结果；
- Graph draft、validation 和 publish 使用明确的完整 Graph document；
- 修正全部 `severity=error` issue；
- publish 后确认 `enabled=true`；
- 用 `/compat/openai/v1/models` 和一次真实 invocation 验证用户可观察行为。

## 8. 交付条件

以下内容组成一次完整交付：

- 用户要求的 topology 和配置已经保存；
- 准备发布的 Graph validation 返回 `valid=true`；
- Workflow 已按任务要求 publish，或用户明确要求保持 draft；
- 所有可达 Agent 使用的 Model Requirement 已绑定；
- 所有可达 Agent、Subagent 和 Command 使用的 MCP Requirement 已绑定，所需 secret slot 不为 `missing`；
- 可达 Python extension 的 dependency status 满足运行条件；
- 至少一次最接近用户需求的真实 invocation 得到可解释结果，或外部阻塞已经明确记录；
- 没有意外遗留的 active Workflow Run；
- 交付报告说明新建或复用的对象、关键 UUID、运行入口、验证结果和未验证项。

## 9. 术语

搜索 API、源码和文档时使用以下产品名称：

- Configuration Repository、Configuration Bundle；
- Model Connection、Model Requirement、Model Mapping；
- MCP Connection、MCP Requirement、MCP Mapping、MCP Tool；
- Main Agent、Subagent、Agent Thread与Run；
- synchronous Subagent、AsyncSubAgent、`async_tasks`；
- Agent Event Output、Workflow Event Output；
- System Prompt、Agent Additional Prompt（AAP）；
- Command、Custom Tool、Custom Middleware；
- Workflow Graph、Node、Edge、handle、State、Runtime、Store；
- Lifecycle、请求入口 Run、被调用 Run、Thread、checkpoint 与 State history；
- Control Edge、`Command.goto`、Super-step、fan-out和loop。

详细字段说明位于 `docs/user-guide/` 和 `docs/wizard-pages/`。本目录负责 AI 的选择入口、操作顺序、运行语义和验收路径，不复制完整字段参考。
