# Workflow、Main Agent 与 Subagent

## 三类 root graph

Agent Shell 在同一个 Agent Server deployment 中注册三类独立 Graph：

- Main Agent：由 LangChain `create_agent()` 与显式 middleware assembly 构造的完整 Agent graph，拥有 AgentState、messages、Thread、Run、checkpoint 和 Agent Event Output。
- Workflow：Start/Command/End control graph，拥有扁平变量的 Workflow State、自己的 Thread/Run/checkpoint 和 Workflow Event Output。
- MCP Tool：Start/Command/End control graph，只通过官方 `/mcp` 被客户端调用；每次调用独立、无 Lifecycle、无 Thread 续聊，也不进入 Model Shell 模型列表。

两者都可以设置为 OpenAI-compatible model 入口。Workflow 需要 AI 时，由 Command 通过 `runtime.context.agent_runs` 启动 Main Agent，或通过节点绑定的 `runtime.context.external_agent` 调用外部 CLI；Agent 本身不嵌入 Canvas。

## Workflow

Workflow metadata 保存 name、description、`is_model_entry`、`on_disconnect` 和可选 Workflow Event Output。Graph document 只允许：

- Start：映射 LangGraph `START`；
- Command：执行配置独占的 async Python，并返回官方 `Command(update, goto)`；
- End：映射 LangGraph `END`；
- Control Edge：连接 Catalog 声明的 `next -> in` endpoint。

Command 的 outgoing Edge 声明允许的目标 Node ID。运行时由脚本返回 `goto="<node-id>"` 选择目标；compiler不会为Command再注册static Edge。Start outgoing Edge才编译为`add_edge(START, target)`。

Workflow State是一张扁平变量表，入口传入的键和Command写回的键都保留在同一个checkpoint里。Command读写`state.get(...)`并返回`update={...}`。Graph document的可选`schema_source`用Python定义Pydantic`State`：声明后入口输入与每个Command的update结果都按它校验，不合法时以`workflow.state_invalid`失败；不声明则不做校验。Agent messages、child State、文件与checkpoint不进入Workflow State。需要child结果时，Command显式调用`agent_runs.check/join`或`workflow_runs.check/join`并把所需值写入自己的`Command.update`。

## MCP Tool

【工作流】页面下同时管理 Workflow 与 MCP Tool。MCP Tool 拥有独立名称、说明、Graph document 和启用状态；名称直接成为官方 `/mcp` 的 tool name，只允许 ASCII 字母、数字、点、下划线和连字符。

发布前先保存 draft。draft 会停止对外可见，但保存 Graph；正式保存会执行完整 validation，并只在成功后创建或刷新官方 Assistant。`/mcp tools/list` 只列出已发布的 MCP Tool，Main Agent 与 Workflow 不会出现。删除 MCP Tool 后对应工具也不再可见。draft 请求被 validation 拒绝时不改变已发布状态，工具继续可见并保持原 Graph。已发布 MCP Tool 引用的 Command 被删除时，该 MCP Tool 自动回到未发布状态并从 `/mcp` 消失；服务重启后按当前 Configuration Repository 的记录重新对齐官方 Assistant。

MCP Tool 的可选 `schema_source` 至少定义 `State`、`Input`、`Output` 三个 Pydantic 模型：

```python
from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str


class State(Input):
    answer: str = ""


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    answer: str
```

`Input` 的每个字段都必须在 `State` 中存在；`Output` 只投影 `State` 的同名字段。没有 schema 时，MCP Tool 接受开放 JSON object，并把参数直接作为扁平 State。`tools/call` 的结果是 Graph 最终值经官方 `/mcp` 返回的 TextContent；它不是 Workflow Event Output 流。

完整Graph与Command契约见[Workflow Graph Canvas Contract](../../.docs/architecture/workflow-graph-canvas-contract.md)和[Command Node](../wizard-pages/command-config.md)。

## Main Agent

Main Agent页面装配：

- 一个Model Requirement；
- Agent Event Output；
- 可选的Filesystem Backend与Filesystem Tools；
- 可选capability refs；
- ordered Custom Tool、Custom Middleware和MCP refs；
- ordered同步Subagent refs；
- root-run设置：`is_model_entry`和`on_disconnect`。

Main Agent UUID 确定稳定 Assistant ID。每次独立调用创建持久Thread；显式续聊在同一Thread创建后续Run并延续AgentState。durability使用Agent Server默认`async`。每个Run创建时还会冻结该Main Agent的【用户断开】策略。

每次用户交互都是新Run。续聊复用Thread，不复用已结束的Run ID。

## 同步 Subagent

Subagent由Main Agent按顺序引用并交给显式 Deep Agents `SubAgentMiddleware`。它定义tool-facing name、description、capability overrides、ordered Tool/Middleware/MCP refs和可选effective Filesystem。

同步Subagent属于Main Agent内部agent loop，不是Workflow Node，也不建立独立Shell archive wrapper。多阶段确定性控制由Workflow和Command表达。

## Agent Additional Prompt

客户端完整请求作为Lifecycle `input/request` envelope保存在Server Store，消息数组位于`request.messages`。Main Agent把验证后的该数组作为Run input进入AgentState；AAP Custom Middleware在Thread首次运行时整理这份AgentState输入，也可显式读取完整请求envelope。

AAP使用checkpointed private initialization marker：一个Agent Thread第一次运行时注入一次；同一Thread后续Run延续既有messages，不重复附加。每次独立执行使用新Thread并各自初始化。

Subagent默认使用Deep Agents delegated messages；是否增加其他材料由该Subagent自己的ordered Middleware决定。详见[Agent Additional Prompt](agent-additional-prompt.md)。

## 事件输出

Main Agent只使用自身装配的Agent Event Output；Workflow只使用自己的Workflow Event Output。Event Output读取原始LangGraph v3 ProtocolEvent与Shell origin，返回空字符串表示隐藏，返回文本表示进入公开response。

Event Output不修改State、checkpoint或Graph routing。公开文本的调度只排列已批准的输出。

## 校验与生效

Main Agent普通保存允许保留装配 error 并设置`enabled=false`；正式保存要求完整装配零 error 后设置`enabled=true`，warning 可以通过。Workflow draft保存只保证wire可解析并设置`enabled=false`；正式保存执行引用、topology、Command package与compile校验后设置`enabled=true`。两类正式保存失败都不覆盖当前记录；新建、复制和Bundle导入均为草稿。

删除被引用的 Component、Subagent 或 Command 时，声明式 UUID 原样保留，受影响的正式 Main Agent/Workflow在同一次配置 mutation 中降级为草稿。Lifecycle 启动前只按`enabled=true`冻结当前正式 Main Agent/Workflow；Component和Subagent继续作为这些正式入口的依赖保留在快照中。capture不重复扫描外部资产或重新判定正式入口有效性，引用资产失效会在真实Graph装配或执行边界返回具体错误。

Chat请求冻结一次Repository与实例资源快照。运行中的配置修改只影响后续Lifecycle。
