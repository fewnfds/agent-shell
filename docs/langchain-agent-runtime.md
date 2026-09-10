# LangChain Agent runtime 基线

Agent Shell 使用锁定的 `langchain==1.4.0`，通过
`langchain.agents.create_agent()` 构造 Main Agent。返回的
`CompiledStateGraph` 直接注册为 `agent-shell-agent` root graph。Deep Agents
继续提供 Filesystem、Skills、增强 Summarization、PatchToolCalls、同步
Subagent、Backend 和 State 等公共组件。

Main Agent 和 Subagent 的完整 middleware 集合由 Agent Shell 根据已校验配置显式装配。
未选择或被 Subagent 设为 `disabled` 的可选能力不进入最终 middleware 列表。

## 责任边界

Agent Shell 拥有 Main Agent、Component、同步 Subagent、Provider Connection、
capability 引用及其装配顺序。LangChain/LangGraph 拥有 Agent loop、模型调用、
Tool execution、Middleware hook、State reducer、Graph 调度与终止。

Deep Agents 公共组件拥有下列行为：

- `FilesystemMiddleware`、`SkillsMiddleware` 与对应 Backend；
- `SummarizationMiddleware` 的模型感知阈值、归档和裁剪；
- `PatchToolCallsMiddleware` 的 tool-call repair；
- `SubAgentMiddleware`、`task` Tool 与 declarative child 编译；
- `DeepAgentState`、`FilesystemState` 及相关 private State contract。

用户 Python Middleware 扩展只返回官方 `AgentMiddleware`。Agent Shell 不建立第二套
model/tool hook 或 Agent loop。

## Main Agent 装配

`runtime/agent_builder.py` 物化 Model、Tool、Backend 和各个 middleware slot，
`runtime/agent_compilation.py` 形成唯一有序列表并调用 `create_agent()`。root constructor
显式接收 model、name、`AgentShellState`、context schema、Store、middleware，以及可选的
system prompt、direct tools 和 response format。

Main Agent middleware 顺序如下：

1. 可选 `SkillsMiddleware`；
2. 可选 `FilesystemMiddleware`；
3. 有直接子级时的 `SubAgentMiddleware`；
4. 可选 Deep Agents `SummarizationMiddleware`；
5. 必选 `PatchToolCallsMiddleware`；
6. 可选 `ModelCallLimitMiddleware`；
7. 可选 `ToolCallLimitMiddleware`；
8. `ToolErrorBoundaryMiddleware`；
9. 可选 `TodoListMiddleware`；
10. 可选 Model Request Settings middleware；
11. `ProviderErrorBoundaryMiddleware`；
12. 可选 Exception Retry middleware；
13. 有固定虚拟文件时的 `AgentInitialFilesMiddleware`；
14. 按配置顺序排列的 Custom Middleware；
15. 可选 `AnthropicPromptCachingMiddleware`。

列表顺序同时决定 wrapper 嵌套和 hook 顺序。LangChain 按正向顺序执行 before hook，
按反向顺序执行 after hook。每个 Run 使用本次装配产生的 middleware 实例。

## 同步 Subagent

只有 Main Agent 保存 direct Subagent UUID。每个 direct child 解析自己的 effective
capability、Tool、Middleware、MCP 和 Filesystem，并投影为 Deep Agents declarative
`SubAgent` dictionary。dictionary 包含 name、description、system prompt、model、tools、
middleware 及可选 response format；当前使用官方默认的 `isolated` mode。

Main Agent 的显式 `SubAgentMiddleware` 持有这些 dictionary spec，并提供 `task` Tool。
Deep Agents 使用 `create_agent()` 编译 child；raw dictionary 形态同时支持 task 调用携带
dynamic response schema 时按该 schema 生成 child runnable。Subagent 不装配 nested
`SubAgentMiddleware` 或 `AgentInitialFilesMiddleware`。

Subagent middleware 顺序如下：

1. 可选 `SkillsMiddleware`；
2. 可选 `FilesystemMiddleware`；
3. 可选 Deep Agents `SummarizationMiddleware`；
4. 必选 `PatchToolCallsMiddleware`；
5. 可选 `ModelCallLimitMiddleware`；
6. 可选 `ToolCallLimitMiddleware`；
7. `ToolErrorBoundaryMiddleware`；
8. 可选 `TodoListMiddleware`；
9. 可选 Model Request Settings middleware；
10. `ProviderErrorBoundaryMiddleware`；
11. 可选 Exception Retry middleware；
12. 按配置顺序排列的 Custom Middleware；
13. `EmptySystemMessageMiddleware`；
14. 可选 `AnthropicPromptCachingMiddleware`。

Deep Agents `0.7.13` 的 declarative child helper 在未配置 system prompt 时传入空字符串。
child-only compatibility middleware 将精确的空 `SystemMessage` 投影为 `None`；所有非空
system content 保持原样。Main Agent 直接使用 `system_prompt=None`，无需该兼容层。

`SubAgentMiddleware` 的 private state keys 从 `AgentShellState`、
`SummarizationState` 和最终 stack 中每个 middleware 的公开 `state_schema` 聚合。
Filesystem 权限直接保存在各 child 的 `FilesystemMiddleware` 实例中。

## 调用限制

`model-call-limit` 与 `tool-call-limit` 分别直接物化 LangChain
`ModelCallLimitMiddleware` 与 `ToolCallLimitMiddleware`。两者都是可选独立 slot，未引用或
被 Subagent 关闭时不进入最终列表。`run_limit` 使用官方 untracked Run state，每次 Agent
invocation 重置；`thread_limit` 使用 private checkpoint state，在同一持久 Main Agent
Thread 的后续 Run 中累计。

同步 Subagent 使用自己的 effective middleware stack。当前 isolated child 没有独立
checkpointer，每次 `task` 调用都从新的 child state 开始，因此 child 的 `thread_limit` 只在
本次 `task` 内累计，与 `run_limit` 具有相同的状态生命周期。Call Limit 的 private state key
会加入 `SubAgentMiddleware.private_state_keys`，child counter 不投影回 parent，因此不会消耗
父 Agent 的 Model/Tool Thread 额度。Tool limit 在模型返回调用后、Tool 执行前拦截超限项。
这些计数与 Graph super-step `recursion_limit` 相互独立。

## Filesystem、Skill 与摘要

Filesystem Backend 与 Filesystem Tools 是两个可选 slot；Subagent 对两者分别继承、替换
或关闭。只有 Backend 与 Tools 同时存在时才构造 `FilesystemMiddleware`。Tools 缺少 Backend
是装配错误；Backend 可以单独作为 Summarization、映射来源或 Custom Middleware 的能力。
Backend 选择 Skill Package 或设置 filesystem system prompt override 时必须同时选择 Tools；
Skill 需要模型可见的 `read_file`。`execute` 只允许与 LocalShellBackend 组合，CompositeBackend
组合在正式保存前直接报告装配错误。

CompositeBackend 的来源权限、只读 `/skills/` route 与请求级 StateBackend 由
`runtime/capabilities/deepagents.py` 物化。LocalShellBackend 使用配置的固定真实
workspace，并可在 Filesystem Tools 显式启用 `execute`。

Deep Agents Summarization 将摘要前的原始消息写入 selected Backend 的
`/conversation_history/{session_uuid}.md`。CompositeBackend 的 default 是请求级
StateBackend；LocalShellBackend 的归档和 large tool result 位于真实 workspace。选择
Summarization 但没有用户 Filesystem Backend 时，Agent Shell 只为该 middleware 提供内部
`StateBackend`，不把它暴露为用户 Filesystem 能力；没有 Filesystem Tools 时模型不能通过
`read_file` 重新读取归档，因此配置校验给出 warning。

没有 `FilesystemMiddleware` 时，大 Tool result 与 Human message 不执行文件卸载，完整内容继续
进入消息上下文；这不会产生卸载阶段错误，但会增加 token 与延迟，并可能最终触发模型供应商的
context window 超限。
`glob` 未以 `/` 锚定的模式递归匹配虚拟文件树，例如 `*.py`；`/*.py` 只匹配虚拟根目录。

## State、Thread 与输出

`AgentShellState` 组合 Deep Agents/LangGraph 的 Agent 与 Filesystem State，并只增加
Agent Shell 所需的 private channel。Main Agent root Run 使用自己的 Thread、checkpoint
和 AgentState。同步 Subagent 使用 delegated private state；Workflow Command 通过公共
Run facade 创建独立 Main Agent Thread/Run。

固定虚拟文件由 `AgentInitialFilesMiddleware` 在每个 Main Agent Thread 首次执行时播种。
Agent Event Output 消费原始 LangGraph v3 ProtocolEvent，并由配置独占的 Python package
投影公开文本。LangChain `create_agent()` 提供 `ToolCallTransformer` 与
`SubagentTransformer`；LangSmith metadata 使用 `langchain_create_agent` integration 分类。

## 依赖升级

升级 LangChain 或 Deep Agents 时，按 [Deep Agents 公共组件接入清单](deep-agents-customizations.md)
复核 constructor、middleware 签名与顺序、declarative SubAgent fields、Backend/State、
trace policy、摘要归档和 v3 event namespace。只为 Agent Shell 拥有的装配与转换保留测试。
