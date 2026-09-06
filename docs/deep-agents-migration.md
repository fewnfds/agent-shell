# Deep Agents runtime 基线

Agent Shell 使用锁定的`deepagents==0.7.11`和`deepagents.create_deep_agent()`构造 Main Agent。返回的`CompiledStateGraph`直接注册为`agent-shell-agent`root graph。直接 Subagent 通过 Deep Agents 官方 dictionary 配置交给`SubAgentMiddleware`；Async Subagent 配置引用投影为带`graph_id`的官方 dictionary，并交给`AsyncSubAgentMiddleware`。两种委派均由 Deep Agents 构造和调度，Shell 不实现第二套 Agent loop。

## 责任边界

Agent Shell 保留 Main Agent、组件、同步 Subagent、Async Subagent 配置资源和 Provider secret 的完整装配能力，并由`deepagents.create_deep_agent()`构造 compiled graph。Main Agent root Run 直接使用自己的 AgentState、Thread 和 Run；Workflow Command 通过公共 Run facade 创建独立 Main Agent Thread/Run。

Deep Agents/LangGraph 负责模型循环、工具执行、同步委派、summarization、tool-call repair、prompt caching、
state reducer、Middleware Hook、`Command`、错误传播和 graph 终止。

用户Python Middleware扩展只返回官方`AgentMiddleware`。Shell不执行prepare、fixed-delay lifecycle或complete，不建立第二套model/tool/agent Hook。AgentState与Workflow State分别由各自Graph和LangGraph Dev的Thread/checkpoint owner持久化。

## 装配

- `enabled=true` 且 `is_model_entry=true` 的 Workflow name，以及 `is_model_entry=true` 的 Main Agent name，均可成为公开 model ID；两类 entry 的规范化名称不得冲突；
- Main Agent root-run 配置保存`durability=sync|async|exit`、`on_disconnect=cancel|continue`和`checkpoint_mode=enabled|disabled`。durability 原样进入官方 Run API，在界面称为【checkpoint 保存时机】；checkpoint disabled 使用官方 Stateless Run（`thread_id=None`），不把 constructor 的`checkpointer`参数当作产品持久化开关；每个 Run 在 relation 中冻结自己的用户断开策略；
- Main Agent 必须有模型要求与 Agent Event Output；模型要求在模型映射页绑定模型连接后才能运行；
- 只有 Main Agent 保存直接 Subagent UUID，Subagent contract 没有 child 引用；
- Main Agent 必须分别选择 Filesystem Backend 与 Filesystem Tools；Subagent 对两者分别继承或替换，不能关闭 required capability，Workflow 不保存 Filesystem ref；
- Subagent 能力按 inherit/replace/disabled 解析，并投影为官方 `CompiledSubAgent` 字典 spec；
- Async Subagent 是保存`component_name`、模板 Main Agent、代理角色名和说明的配置资源；Main Agent 的`async_subagents`按顺序只保存其 UUID。只有 Main Agent 显式选择 Async Subagent Middleware component 后才将有效引用投影为官方`AsyncSubAgent` spec；`graph_id`是模板 Main Agent 的稳定 Assistant ID，同部署省略`url`和`headers`；
- 每个Main Agent Run按自己的effective Backend与Tools构造FilesystemMiddleware。CompositeBackend的每条来源直接声明权限，并可通过`skill_package_id`引用Skill独立包、建立只读`/skills/`route；LocalShellBackend直接使用一个固定真实workspace，不接受Composite来源或Skill包；
- Skill Component 只制作独立包，不进入 Agent capability refs。Skill 包引用随 CompositeBackend 一起被 Subagent 继承或替换；
- `execute` 在 Filesystem Tools 中默认关闭；开启后仅 LocalShellBackend 提供该工具，CompositeBackend 由 Deep Agents 按 Backend 能力隐藏它；
- Deep Agents 将摘要前的原始消息写入 selected backend 的 `/conversation_history/{session_uuid}.md`。Composite 配置的 default backend 是请求级 StateBackend；LocalShell 配置直接使用真实 workspace，因此 conversation history 与 large tool result 会写入该 workspace。LocalShell 不叠加 StateBackend route，避免 Deep Agents 为 Composite + execute 无条件追加虚拟路径映射系统提示词；该 session UUID 只隔离 parallel Agent 的内部归档，Shell 不读取、命名或把它映射为 Lifecycle/thread conversation history；
- `glob` 未以 `/` 锚定的模式递归匹配虚拟文件树，例如 `*.py`；`/*.py` 才只匹配虚拟根目录；
- Summarization 与 Prompt Caching 是两个独立 capability，每个身份显式物化自己的官方 middleware；
- Agent Shell 传给 `create_deep_agent(middleware=...)` 的 caller 列表属于官方 User slot：同名的 Summarization/Prompt Caching replacement 在各自默认位置生效，Todo replacement 和 `custom-middleware` 按用户列表顺序进入 User slot；
- Deep Agents `0.7.9+` 的 Filesystem、Skills、SubAgent、Summarization 和 PatchToolCalls Middleware 默认以 `TracePolicy(process_inputs=omit_payload)` 裁剪 hook inputs。Agent Shell 使用这些官方默认或同名 replacement 自带的官方策略；运行监控在root Graph的LangChain ChatModel和post-transformer v3边界采集，不修改Middleware实例、类属性或进程级trace policy；
- Deep Agents 仍按 Base -> User -> Tail 的固定 stack 合并。新名称不能越过 profile、provider prompt caching、memory 或 HITL 等官方 Tail；同名 replacement 也不会从最终 middleware 列表物理移除；
- Main Agent 未选择、或 Subagent 选择 `disabled` 的可选 default Middleware，必须保留为主动禁用状态，并以官方支持的 same-name
  no-op replacement 阻止 Deep Agents 默认 stack 回填；仅省略 constructor 参数不表示禁用；
- `AgentShellState`只扩展Agent自身需要的private channel；Workflow业务变量只存在于独立`WorkflowState.shared_vars`。Middleware实例属性只保存当前实例的运行期数据。
- Agent Event Output 使用 `agent-event-output` 的 configuration-owned Python package，脚本通过同步 `output(event, origin)` 读取原始 LangGraph v3 ProtocolEvent 与明确的 Shell origin 返回公开文本。

### Middleware 禁用装配查证表（deepagents 0.7.11）

以下是 current Agent Shell 装配中会使用“同名、无行为 replacement”的能力。replacement 是通过 `create_deep_agent(middleware=...)` 的官方同名覆盖规则生效的；它会替换默认实例，但不会让该名称从最终 middleware 列表中消失。

| Agent Shell capability | Deep Agents middleware name | 触发 replacement 的情况 | 最终是否物理移除 |
| --- | --- | --- | --- |
| `todo-list` | `TodoListMiddleware` | Main 未选择；或 Subagent 选择 `disabled`；也覆盖当前 Codex harness profile 的额外 Todo | 否，保留无行为 placeholder |
| `summarization` | `SummarizationMiddleware` | Main 未选择；或 Subagent 选择 `disabled` | 否，保留无行为 placeholder |
| `prompt-caching` | `AnthropicPromptCachingMiddleware` | Main 未选择；或 Subagent 选择 `disabled` | 否，保留无行为 placeholder |

当前核心依赖只装配 Anthropic Prompt Caching replacement；如果未来启用 Deep Agents 的 Bedrock、Fireworks 等额外 provider middleware，必须为新增的 middleware name 增加对应 replacement 和回归测试。

下列项目不走这套 replacement：

- `SubAgentMiddleware`：通过官方 `GeneralPurposeSubagentProfile(enabled=False)` 且不传 synchronous Subagent，真正不装配；有直接 Subagent 时使用同名 replacement 固定 private State keys，并保留 replacement 的官方 trace policy；
- `AsyncSubAgentMiddleware`：未选择 Async Subagent Middleware component 时不传 async spec，真正不装配；选择 component 与有效引用时用官方同名 replacement 应用 system prompt 和 Tool description override，并额外装配 Shell relation observer；
- `FilesystemMiddleware`：官方要求的 protected scaffolding，不能移除，只能限制其工具或权限；
- `PatchToolCallsMiddleware`：当前是 Deep Agents 核心修复 middleware，没有 Agent Shell 的可选禁用开关；Shell 使用同名行为实例承接 Run-local trace policy。

Deep Agents 也支持 `HarnessProfile.excluded_middleware` 物理移除普通 middleware，但它是按 model/provider profile 生效，无法表达同一模型下每个 Agent 独立的 capability 选择，因此当前运行时没有用它承载上述 per-agent 设置。

Agent Filesystem 的 mapped directories 可接入 Deep Agents `FilesystemBackend`。LangChain 官方文档把 `FilesystemBackend` 列为不适合 Web server/HTTP API 的 backend，本项目按该上游限制管理使用场景。
如果未来要消除该限制，应按官方建议改用 `StateBackend`、`StoreBackend` 或 sandbox backend，并另立需求，不在本次 ctx 迁移中偷偷替换。
`LocalShellBackend` 还提供直接宿主命令执行，没有 sandbox；`virtual_mode=True` 只约束文件工具的路径解析，不能限制命令访问服务账号可达的其他文件、进程、网络或系统资源。

Main Agent root Run 直接以官方 `input.messages` 更新 AgentState。AAP 的 private checkpoint marker 使每个已装配 AAP 只在同一 Main Agent Thread 的第一次执行时初始化消息；后续 Run延续现有 messages，不重复追加。固定虚拟文件也用 private marker 每个 Thread 只播种一次。synchronous Subagent 默认从 delegated private `state.messages` 整理 input，并拥有自己的 middleware state scope。

Canvas Start/End只是LangGraph官方virtual `START/END`。Workflow入口的client `messages[]`冻结在application-level LangGraph Store的Lifecycle namespace；不会由Start注入或进入Workflow root State。Main Agent入口的client messages直接作为官方Run input进入AgentState；选择AAP时，其官方`before_agent`Hook从current AgentState messages开始整理，未选择AAP时保留官方input语义。

synchronous Subagent 是 Agent 内部的官方`SubAgentMiddleware` capability。Async Subagent 在显式选择 Middleware component 后复用`create_deep_agent(subagents=[...])`的官方 assembly 入口；Deep Agents 按`graph_id`识别 async spec 并增加五个 task 工具。父 Agent 的`async_tasks`专用 State channel 保存 task/thread/run reference，stateful 父 Thread 的后续 Run 可继续管理既有 task。

同部署 Async Subagent 使用 ASGI transport，并为每个 task 创建独立 Thread/Run。Shell 在父 Run 开始前物化可达模板 Assistant 闭包。child 本身不携带 Shell Lifecycle metadata；关联 Middleware 通过公开 ToolRuntime 与返回 Command 的 identity 把 child 登记进统一 relation，使 monitoring、用户断开处理和 retention 覆盖它。child 原始 stream 不进入父 Lifecycle response，父 Agent check 后写入回复的结果才经父 Agent Event Output 公开。child Thread checkpoint 固定启用，durability 使用官方默认`async`；一个 active 父 Run 与每个 active child 各占一个 worker slot，`n_jobs_per_worker`应覆盖实际并发总数。

Workflow Command可通过 `runtime.context.agent_runs` 创建独立 Main Agent Assistant/Thread/Run，通过 `workflow_runs`创建独立 Workflow Run。Main Agent默认创建新 Thread；同一 Lifecycle显式提供该 Main Agent既有 Thread可创建新 Run并延续 AgentState。每个被调用 Run由 LangGraph Dev dynamic factory使用冻结配置装配；Server-managed路径使用 LangGraph Dev注入的 Store和 checkpoint owner。每个 Run持有自己的 package runtime与 Event Output projector；状态和结果通过公共 Run API读取，Lifecycle Store只保存最小关系。

更新 Deep Agents 版本时重新核对 `create_deep_agent` constructor、同步/异步 dictionary SubAgent fields、Async Subagent 五个工具与`async_tasks` schema、default Middleware、same-name replacement 与 `HarnessProfile.excluded_middleware`、各 Provider Prompt Caching 变体、Codex TodoList extra Middleware、backend/state transfer、摘要归档的 session 隔离、`glob` 语义和 v3 event namespace，并只为 Shell 自有转换保留行为测试。
