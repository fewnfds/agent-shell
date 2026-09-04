# Deep Agents runtime 基线

Agent Shell 使用锁定的 `deepagents==0.7.11` 和 `deepagents.create_deep_agent()` 构造 Main Agent。直接 Subagent 通过 Deep Agents 官方 dictionary 配置交给 `SubAgentMiddleware`，由 Deep Agents 构造和调度；Shell 只在外层 canvas Agent Node 建立 invocation identity 和 parent/child State 输入输出边界，不实现委派调度或第二套 Agent loop。

## 责任边界

Agent Shell 保留 Main Agent、组件、直接 Subagent 和 Provider secret 的完整装配能力，并由 `deepagents.create_deep_agent()` 构造 compiled graph。current Workflow 的 Agent Node 引用完整 Main Agent，由 parent Graph wrapper 通过公开 `ainvoke()` 显式建立 parent/child State 输入输出边界。

Deep Agents/LangGraph 负责模型循环、工具执行、同步委派、summarization、tool-call repair、prompt caching、
state reducer、Middleware Hook、`Command`、错误传播和 graph 终止。

用户 Python 扩展只返回官方 `AgentMiddleware`。Shell 不执行 prepare、fixed-delay lifecycle 或 complete，不建立第二套 model/tool/agent Hook。Workflow State 业务数据通过官方 state update 写入 `AgentShellState`；Workflow 装配 Checkpointer 时，这些 State update 才进入官方 checkpoint。

## 装配

- 全部 enabled Workflow name 都是公开 model ID；Main Agent 引用保存在 Graph Agent Node config，不在 Workflow metadata 中；
- Main Agent 必须有模型要求与 Agent Event Output；模型要求在模型映射页绑定模型连接后才能运行；
- 只有 Main Agent 保存直接 Subagent UUID，Subagent contract 没有 child 引用；
- Main Agent 必须分别选择 Filesystem Backend 与 Filesystem Tools；Subagent 对两者分别继承或替换，不能关闭 required capability，Workflow 不保存 Filesystem ref；
- Subagent 能力按 inherit/replace/disabled 解析，并投影为官方 `CompiledSubAgent` 字典 spec；
- 同一次 Workflow 请求共享 Deep Agents StateBackend 文件状态；每个 Main Agent/Subagent 按自己的 effective Backend 与 Tools 构造 FilesystemMiddleware。CompositeBackend 的每条来源直接声明权限，并可通过 `skill_package_id` 引用 Skill 独立包、建立只读 `/skills/` route；LocalShellBackend 直接使用一个固定真实 workspace，不接受 Composite 来源或 Skill 包；
- Skill Component 只制作独立包，不进入 Agent capability refs。Skill 包引用随 CompositeBackend 一起被 Subagent 继承或替换；
- `execute` 在 Filesystem Tools 中默认关闭；开启后仅 LocalShellBackend 提供该工具，CompositeBackend 由 Deep Agents 按 Backend 能力隐藏它；
- Deep Agents 将摘要前的原始消息写入 selected backend 的 `/conversation_history/{session_uuid}.md`。Composite 配置的 default backend 是请求级 StateBackend；LocalShell 配置直接使用真实 workspace，因此 conversation history 与 large tool result 会写入该 workspace。LocalShell 不叠加 StateBackend route，避免 Deep Agents 为 Composite + execute 无条件追加虚拟路径映射系统提示词；该 session UUID 只隔离 parallel Agent 的内部归档，Shell 不读取、命名或把它映射为 Lifecycle/thread conversation history；
- `glob` 未以 `/` 锚定的模式递归匹配虚拟文件树，例如 `*.py`；`/*.py` 才只匹配虚拟根目录；
- Summarization 与 Prompt Caching 是两个独立 capability，每个身份显式物化自己的官方 middleware；
- Agent Shell 传给 `create_deep_agent(middleware=...)` 的 caller 列表属于官方 User slot：同名的 Summarization/Prompt Caching replacement 在各自默认位置生效，Todo replacement 和 `custom-middleware` 按用户列表顺序进入 User slot；
- Deep Agents `0.7.9+` 的 Filesystem、Skills、SubAgent、Summarization 和 PatchToolCalls Middleware 默认以 `TracePolicy(process_inputs=omit_payload)` 裁剪 hook inputs。Agent Shell 使用这些官方默认或同名 replacement 自带的官方策略；运行监控只在 Workflow root 的 LangChain ChatModel 和 post-transformer v3 边界采集，不修改 Middleware 实例、类属性或进程级 trace policy；
- Deep Agents 仍按 Base -> User -> Tail 的固定 stack 合并。新名称不能越过 profile、provider prompt caching、memory 或 HITL 等官方 Tail；同名 replacement 也不会从最终 middleware 列表物理移除；
- Main Agent 未选择、或 Subagent 选择 `disabled` 的可选 default Middleware，必须保留为主动禁用状态，并以官方支持的 same-name
  no-op replacement 阻止 Deep Agents 默认 stack 回填；仅省略 constructor 参数不表示禁用；
- `AgentShellState.shared_vars` 保存公共 Workflow State 业务变量；Workflow 装配 Checkpointer 时它参与官方 checkpoint，Middleware 实例属性只保存当前实例的运行期数据。
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
- `FilesystemMiddleware`：官方要求的 protected scaffolding，不能移除，只能限制其工具或权限；
- `PatchToolCallsMiddleware`：当前是 Deep Agents 核心修复 middleware，没有 Agent Shell 的可选禁用开关；Shell 使用同名行为实例承接 Run-local trace policy。

Deep Agents 也支持 `HarnessProfile.excluded_middleware` 物理移除普通 middleware，但它是按 model/provider profile 生效，无法表达同一模型下每个 Agent 独立的 capability 选择，因此当前运行时没有用它承载上述 per-agent 设置。

Agent Filesystem 的 mapped directories 可接入 Deep Agents `FilesystemBackend`。LangChain 官方文档把 `FilesystemBackend` 列为不适合 Web server/HTTP API 的 backend，本项目按该上游限制管理使用场景。
如果未来要消除该限制，应按官方建议改用 `StateBackend`、`StoreBackend` 或 sandbox backend，并另立需求，不在本次 ctx 迁移中偷偷替换。
`LocalShellBackend` 还提供直接宿主命令执行，没有 sandbox；`virtual_mode=True` 只约束文件工具的路径解析，不能限制命令访问服务账号可达的其他文件、进程、网络或系统资源。

Canvas Start/End 只是 LangGraph 官方 virtual `START/END`。client `messages[]` 冻结在 application-level LangGraph Store 的 Lifecycle namespace；不会由 Start 注入、进入 root State 或自动成为 Main Agent active messages。选择 Agent Additional Prompt（AAP）Custom Middleware 时，已装配的官方 `before_agent` Hook 为 Main Agent 用 `runtime.context.lifecycle_id` 从 `runtime.store` 读取 input；Main Agent 未选择 AAP 时 initial `messages` 保持空。synchronous Subagent 默认从 delegated private `state.messages` 整理 input，不自动混入 root request。

synchronous Subagent 是 Agent 内部的官方 `SubAgentMiddleware` capability，不与 outer Workflow 竞争 scheduling responsibility。后续 AsyncSubAgent 使用 `create_deep_agent(subagents=[AsyncSubAgent(...)])` 的官方 assembly entry，并单独处理 `graph_id`、Agent Protocol 地址、认证和官方异步任务 State。

跨 Workflow 调用通过 `runtime.context.workflow_runs` 创建独立的官方 Assistant、Thread 和 Run。每个被调用 Run 由 LangGraph Dev dynamic factory 使用自己的冻结 Workflow 配置装配 `AgentRuntime`/`AgentBuilder`，并可继续调用其他 Workflow；Server-managed 路径使用 LangGraph Dev 注入的 Store 和 checkpoint owner，不读取 Workflow `checkpointer_id`。Canvas Agent/Deep Agent subgraph 不覆写 saver，按 LangGraph 默认继承所在 Workflow root 的 Checkpointer。每个 Run 持有自己的 Middleware package runtime 和 Event Output projector；已投影事件作为平等 producer 进入当前公开 response 的 Lifecycle scheduler，Run 状态和结果通过公共 Run API 读取。

更新 Deep Agents 版本时重新核对 `create_deep_agent` constructor、dictionary SubAgent field、default Middleware、same-name replacement 与 `HarnessProfile.excluded_middleware`、各 Provider Prompt Caching 变体、Codex TodoList extra Middleware、backend/state transfer、摘要归档的 session 隔离、`glob` 语义、StateGraph subgraph 组合和 v3 event namespace，并只为 Shell 自有转换保留行为测试。
