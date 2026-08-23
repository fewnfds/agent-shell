# Deep Agents runtime 基线

Agent Shell 使用锁定的 `deepagents==0.7.7` 和 `deepagents.create_deep_agent()` 构造 Main Agent。直接 Subagent 通过 Deep Agents 官方 dictionary 配置交给 `SubAgentMiddleware`，由 Deep Agents 构造和调度；Shell 只在外层画布 Main Agent node 建立 invocation identity 和父子 State 输入输出边界，不实现委派调度或第二套 Agent loop。

## 责任边界

Agent Shell 保留 Main Agent、组件、直接 Subagent 和 Provider secret 的完整装配能力，并由 `deepagents.create_deep_agent()` 构造 compiled graph。当前 Workflow Agent node 引用完整 Main Agent，由父图 wrapper 通过公开 `ainvoke()` 显式建立父子 State 输入输出边界。

Deep Agents/LangGraph 负责模型循环、工具执行、同步委派、summarization、tool-call repair、prompt caching、
state reducer、Middleware Hook、`Command`、错误传播和 graph 终止。

用户 Python 扩展只返回官方 `AgentMiddleware`。Shell 不执行 prepare、fixed-delay lifecycle 或 complete，不建立第二套 model/tool/agent Hook。需要 checkpoint 的业务数据通过官方 state update 写入 `AgentShellState`。

## 装配

- 启用的父图 Workflow 名称是公开 model ID；子图名称不进入 `/v1`；Main Agent 引用保存在 Graph Agent node config，不在 Workflow metadata 中；
- Main Agent 必须有模型要求与 Agent 事件输出；模型要求在模型映射页绑定模型连接后才能运行；
- 只有 Main Agent 保存直接 Subagent UUID，Subagent contract 没有 child 引用；
- Main Agent 可选择项目 Filesystem 或最小 Filesystem；Subagent 可继承、选择自己的项目 Filesystem 或回到最小 Filesystem，Workflow 不保存 Filesystem ref；
- Subagent 能力按 inherit/replace/disabled 解析，并投影为官方 `CompiledSubAgent` 字典 spec；
- 同一次 Workflow 请求共享 Deep Agents StateBackend 文件状态；每个 Main Agent/Subagent 按自己的 Filesystem、
  `filesystem-permissions` 与 file-tool override 构造 backend 路由视图；选择 Skill 时还会建立独立只读的 `/skills/` 路由，并参与保留命名空间冲突校验；
- Deep Agents 将摘要前的原始消息写入默认 backend 的保留 `/conversation_history/{session_uuid}.md`；该 session UUID 只隔离并行 Agent 的内部归档，Shell 不读取、命名或把它映射为 Lifecycle/thread 对话历史；
- `glob` 未以 `/` 锚定的模式递归匹配虚拟文件树，例如 `*.py`；`/*.py` 才只匹配虚拟根目录；
- Summarization 与 Prompt Caching 是两个独立 capability，每个身份显式物化自己的官方 middleware；
- Agent Shell 传给 `create_deep_agent(middleware=...)` 的 caller 列表属于官方 User slot：同名的 Summarization/Prompt Caching replacement 在各自默认位置生效，Todo replacement 和 `custom-middleware` 按用户列表顺序进入 User slot；
- Deep Agents 仍按 Base -> User -> Tail 的固定 stack 合并。新名称不能越过 profile、provider prompt caching、memory 或 HITL 等官方 Tail；同名 replacement 也不会从最终 middleware 列表物理移除；
- Main Agent 未选择、或 Subagent 选择 `disabled` 的可选默认 Middleware，必须保留为主动禁用状态，并以官方支持的同名
  no-op replacement 阻止 Deep Agents 默认 stack 回填；仅省略 constructor 参数不表示禁用；
- `AgentShellState.shared_vars` 保存公共 checkpointed 业务变量；Middleware 实例属性保存当前实例的运行期数据。
- Agent 事件输出使用 `agent-event-output` 的 configuration-owned Python package，脚本通过同步 `output(event)` 返回公开文本。

### Middleware 禁用装配查证表（deepagents 0.7.7）

以下是当前 Agent Shell 装配中会使用“同名、无行为 replacement”的能力。replacement 是通过 `create_deep_agent(middleware=...)` 的官方同名覆盖规则生效的；它会替换默认实例，但不会让该名称从最终 middleware 列表中消失。

| Agent Shell capability | Deep Agents middleware name | 触发 replacement 的情况 | 最终是否物理移除 |
| --- | --- | --- | --- |
| `todo-list` | `TodoListMiddleware` | Main 未选择；或 Subagent 选择 `disabled`；也覆盖当前 Codex harness profile 的额外 Todo | 否，保留无行为 placeholder |
| `summarization` | `SummarizationMiddleware` | Main 未选择；或 Subagent 选择 `disabled` | 否，保留无行为 placeholder |
| `prompt-caching` | `AnthropicPromptCachingMiddleware` | Main 未选择；或 Subagent 选择 `disabled` | 否，保留无行为 placeholder |

当前核心依赖只装配 Anthropic Prompt Caching replacement；如果未来启用 Deep Agents 的 Bedrock、Fireworks 等额外 provider middleware，必须为新增的 middleware name 增加对应 replacement 和回归测试。

下列项目不走这套 replacement：

- `SubAgentMiddleware`：通过官方 `GeneralPurposeSubagentProfile(enabled=False)` 且不传同步 Subagent，真正不装配；
- `FilesystemMiddleware`：官方要求的 protected scaffolding，不能移除，只能限制其工具或权限；
- `PatchToolCallsMiddleware`：当前是 Deep Agents 核心修复 middleware，没有 Agent Shell 的可选禁用开关。

Deep Agents 也支持 `HarnessProfile.excluded_middleware` 物理移除普通 middleware，但它是按 model/provider profile 生效，无法表达同一模型下每个 Agent 独立的 capability 选择，因此当前运行时没有用它承载上述 per-agent 设置。

Agent Filesystem 的 mapped directories 可接入 Deep Agents `FilesystemBackend`。LangChain 官方文档把 `FilesystemBackend` 列为不适合 Web server/HTTP API 的 backend，本项目按该上游限制管理使用场景。
如果未来要消除该限制，应按官方建议改用 `StateBackend`、`StoreBackend` 或 sandbox backend，并另立需求，不在本次 ctx 迁移中偷偷替换。

Canvas Start/End 只是 LangGraph 官方虚拟 `START/END`。客户端 `messages[]` 冻结在应用级 LangGraph Store 的 Lifecycle namespace；不会由 Start 注入、进入 root State 或自动成为 Main Agent 活动消息。只有选择 Workflow Input Context 这类 Custom Middleware 时，已装配的官方 `before_agent` Hook 才会为 Main Agent 用 `runtime.context.lifecycle_id` 从 `runtime.store` 读取输入；未选择时 Agent 的初始 `messages` 保持空。同步 Subagent 默认从其 delegated private `state.messages` 整理输入，不自动混入根请求。

同步 Subagent 是 Agent 内部的官方 `SubAgentMiddleware` 能力，不与外层 Workflow 竞争调度职责。后续 AsyncSubAgent 使用 `create_deep_agent(subagents=[AsyncSubAgent(...)])` 的官方装配入口，并单独处理 `graph_id`、
Agent Protocol 地址、认证和后台 task state。

外层后台 Workflow 由 Shell 应用级 Manager 管理 detached execution handle/status，child 由 Workflow runtime 构造，并为每个并发 child 新建独立 `AgentRuntime`/`AgentBuilder`。child 共享官方 Store 与 checkpointer 服务，各自持有 Builder 的 Middleware package runtime，并通过独立查询接口提供事件。

更新 Deep Agents 版本时重新核对 `create_deep_agent` constructor、dictionary SubAgent 字段、默认 Middleware、同名 replacement 与 `HarnessProfile.excluded_middleware`、各 provider Prompt Caching 变体、Codex TodoList extra middleware、backend/state transfer、摘要归档的 session 隔离、`glob` 语义、StateGraph subgraph 组合和 v3 事件 namespace，并只为 Shell 自有转换保留行为测试。
