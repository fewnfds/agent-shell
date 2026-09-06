# Workflow、Main Agent 与 Subagent

## 两类 root graph

Agent Shell 在同一个 Agent Server deployment 中注册两类独立 Graph：

- Main Agent：完整 Deep Agents graph，拥有 AgentState、messages、Thread、Run、checkpoint 和 Agent Event Output。
- Workflow：Start/Command/End control graph，拥有只含 `shared_vars` 的 Workflow State、自己的 Thread/Run/checkpoint 和 Workflow Event Output。

两者都可以设置为 OpenAI-compatible model 入口。Workflow 需要 AI 时，由 Command 通过 `runtime.context.agent_runs` 启动 Main Agent，不把 Agent 嵌入 Canvas。

## Workflow

Workflow metadata 保存 name、description、`is_model_entry`、`durability`、`on_disconnect` 和可选 Workflow Event Output。Graph document 只允许：

- Start：映射 LangGraph `START`；
- Command：执行配置独占的 async Python，并返回官方 `Command(update, goto)`；
- End：映射 LangGraph `END`；
- Control Edge：连接 Catalog 声明的 `next -> in` endpoint。

Command 的 outgoing Edge 声明允许的目标 Node ID。运行时由脚本返回 `goto="<node-id>"` 选择目标；compiler不会为Command再注册static Edge。Start outgoing Edge才编译为`add_edge(START, target)`。

Workflow State只有`shared_vars`。Agent messages、child State、文件与checkpoint不进入Workflow State。需要child结果时，Command显式调用`agent_runs.check/join`或`workflow_runs.check/join`并把所需值写入自己的`Command.update`。

完整Graph与Command契约见[Workflow Graph Canvas Contract](../../.docs/architecture/workflow-graph-canvas-contract.md)和[Command Node](../wizard-pages/command-config.md)。

## Main Agent

Main Agent页面装配：

- 一个Model Requirement；
- Agent Event Output；
- Filesystem Backend与Filesystem Tools；
- 可选capability refs；
- ordered Custom Tool、Custom Middleware和MCP refs；
- ordered同步Subagent refs；
- ordered Async Subagent configuration refs；
- root-run设置：`is_model_entry`、`checkpoint_mode`、`durability`和`on_disconnect`。

Main Agent UUID 确定稳定 Assistant ID。`checkpoint_mode=enabled`时，同一 Thread 上的后续新 Run 延续 AgentState；`disabled`使用 stateless Run，不承诺跨 Run 消息或 private marker 连续性。`durability=sync|async|exit`直接传给官方 Run，界面名称为【checkpoint 保存时机】。每个 Run 创建时还会冻结该 Main Agent 的【用户断开】策略。

每次用户交互都是新Run。续聊复用Thread，不复用已结束的Run ID。

## 同步 Subagent

Subagent由Main Agent按顺序引用并交给Deep Agents官方SubAgent Middleware。它定义tool-facing name、description、capability overrides、ordered Tool/Middleware/MCP refs和effective Filesystem。

同步Subagent属于Main Agent内部agent loop，不是Workflow Node，也不建立独立Shell archive wrapper。多阶段确定性控制由Workflow和Command表达。

## Async Subagent

【代理 / Async Subagent】创建可复用配置资源：填写配置名称，选择模板 Main Agent，并填写模型可见的代理角色名和说明。该资源只是引用外壳，不复制模板装配，也不创建第二个 Agent Graph。Main Agent 的`async_subagents`按顺序只保存这些资源的 UUID；同一资源不能重复引用，模板不能指回引用方，所有有效角色名按大小写不敏感语义唯一。

Main Agent 必须另外显式选择【Async Subagent / 异步子代理】组件，引用才会成为有效装配。没有选择组件时，引用只作为候选配置保存，不提供异步工具；选择组件但没有引用时保存失败。组件可以覆盖 Middleware system prompt 与五个官方 Tool description，并继续复用官方工具实现、参数 schema 和`async_tasks` State contract。

Deep Agents 为有效装配提供`start_async_task`、`check_async_task`、`update_async_task`、`cancel_async_task`和`list_async_tasks`。Launch 立即返回 task ID，并在同一 Agent Server 中创建独立 child Thread/Run；Update 在该 child Thread 上创建新 Run。目标使用模板 Main Agent 的稳定 Assistant ID，ASGI transport 不需要另配 URL 或认证。

父 Agent 的`async_tasks` channel 保存 task reference。checkpoint enabled 父 Thread 的后续 Run 可以继续 check、update 或 cancel；checkpoint disabled 父 Run 结束后不保留这些 reference。child 自己的 Thread checkpoint 固定启用，checkpoint 保存时机固定使用官方默认`async`；child Run 创建时冻结模板 Main Agent 的【用户断开】策略，并进入父 Lifecycle 的 monitoring 与 retention。child 原始 stream 不加入父 Lifecycle 公开输出；父 Agent check 结果并写入自己的回复后，结果才经父 Agent Event Output 返回。一个父 Run 和每个 active child 分别占用一个`n_jobs_per_worker`槽位。

## Agent Additional Prompt

客户端messages作为Main Agent Run input进入AgentState，并作为Lifecycle输入快照保存在Server Store。AAP Custom Middleware在Thread首次运行时整理这份AgentState输入。

AAP使用checkpointed private initialization marker：一个stateful Agent Thread第一次运行时注入一次；同一Thread后续Run延续既有messages，不重复附加。Stateless Run没有跨Runmarker，因此每次独立执行都初始化。

Subagent默认使用Deep Agents delegated messages；是否增加其他材料由该Subagent自己的ordered Middleware决定。详见[Agent Additional Prompt](agent-additional-prompt.md)。

## 事件输出

Main Agent只使用自身装配的Agent Event Output；Workflow只使用自己的Workflow Event Output。Event Output读取原始LangGraph v3 ProtocolEvent与Shell origin，返回空字符串表示隐藏，返回文本表示进入公开response。

Event Output不修改State、checkpoint或Graph routing。公开文本的调度只排列已批准的输出。

## 校验与生效

Main Agent/Subagent编辑页提交完整草稿并由后端校验装配。Workflow draft保存只保证wire可解析并设置`enabled=false`；正式保存执行引用、topology、Command package与compile校验后设置`enabled=true`。

Chat请求冻结一次Repository与实例资源快照。运行中的配置修改只影响后续Lifecycle。
