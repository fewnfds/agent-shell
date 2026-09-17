# Command Node

Command Node 是在 Workflow control graph 中执行确定性 Python 的 programmable Node。它读取当前 Workflow State 和 Runtime Context，直接返回官方 `langgraph.types.Command(update=..., goto=...)`。

## Package 与入口

模板位于 `data/templates/workflow/command/<template-key>/`，内置示例位于 `examples/workflow-components/command/<example-key>/`。配置保存后拥有独立的 `python_packages/command/<configuration-name>/` 目录和 `family: workflow-node`、`adapter: command` manifest。

`main.py` 提供同步无参工厂 `create_command()`；工厂返回签名为 `async command(state, runtime)` 的 callable：

```python
from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        target = "review" if state.get("needs_review") else "finish"
        return Command(
            update={"selected_target": target},
            goto=target,
        )

    return command
```

文件编辑在下一次物化时生效；`requirements.txt` 变化后重启 Agent Shell 以准备依赖。扩展运行在服务进程的受信任边界内，没有 sandbox。

## 输入

- `state` 是当前 State 的独立副本，键名即变量名。
- `runtime` 是 LangGraph 注入的 `Runtime[WorkflowRuntimeContext]`。
- Shell 身份从 `runtime.context` 读取，包括 Lifecycle、Workflow Run、Workflow、Command Node 和当前 Node invocation。
- 官方 Run/checkpoint/task/retry 信息从 `runtime.execution_info` 读取。
- `runtime.context.agent_runs` 与 `workflow_runs` 提供独立 Graph Run facade。
- `runtime.store` 是 Agent Server Store；只有存在明确 namespace 和 consumer 时才写入。

脚本对传入 `state` 副本的原地修改不会自动提交。所有 State 变化都必须放入返回 Command 的 `update`。

## 内置成功示例

内置 catalog 提供五个职责互补的 Command：

| 模板 | 从哪里取值 | `update` 写回的变量 | `goto` 来源 |
| --- | --- | --- | --- |
| `state-routing-command` | `state.items` 与两个目标 Node ID | `item_count`、`review_item_count`、`selected_target_node_id` | 有待复核项时使用 `review_target_node_id`，否则使用 `complete_target_node_id` |
| `runtime-context-command` | `runtime.context`、`runtime.execution_info`、`state.runtime_target_node_id` | 显式 JSON-compatible `command_runtime.context/execution_info` projection | `runtime_target_node_id` |
| `agent-run-command` | `state.agent_run` 与 `runtime.context.agent_runs` | `agent_run_result` | `agent_run.target_node_id` |
| `workflow-run-command` | `state.workflow_run` 与 `runtime.context.workflow_runs` | `workflow_run_result` | `workflow_run.target_node_id` |
| `antigravity-agent-command` | `state.external_agent_run` 或 Lifecycle `input/request` envelope 中 `request.messages` 的最后一条 `user` 消息，加上 `runtime.context.external_agent` | `external_agent_result` | 无显式 `goto`；沿当前 Command 的 outgoing Edge 自然继续 |

State routing 的成功输入例如：

```json
{
  "items": [
    {"id": "item-1", "requires_review": true},
    {"id": "item-2", "requires_review": false}
  ],
  "review_target_node_id": "manual-review",
  "complete_target_node_id": "publish"
}
```

该输入返回 `item_count=2`、`review_item_count=1` 并
`goto="manual-review"`。`manual-review` 和 `publish` 必须是 Canvas 上真实存在、且
分别由当前 Command outgoing Edge 声明的 Node ID。

Runtime 示例只从 State 读取 `runtime_target_node_id`。Shell 的 request、Lifecycle、
caller Run、Workflow、Node 与 invocation identity 来自 `runtime.context`；官方
checkpoint、Thread、Run、task 与 node attempt 来自 `runtime.execution_info`。模板只把
这些对象的文档化标量字段投影到 `command_runtime`，不会把 facade 或 Runtime 对象写入
State。

Agent Run 示例读取以下控制对象：

```json
{
  "agent_run": {
    "action": "start",
    "target_node_id": "wait-for-agent",
    "main_agent_id": "<main-agent-uuid>",
    "operation_id": "review:artifact-42",
    "input": [{"role": "user", "content": "Review the artifact."}]
  }
}
```

`start` 可额外传 `thread_id` 续接 idle Agent Thread。`check`、`get`、`join`、`cancel`
则读取 `thread_id` 与 `run_id`，并分别调用同名 Agent facade 方法。结果投影到
`agent_run_result.action/run`；`get` 是 `check` 的同语义入口。

Workflow Run 示例的 `start` 读取 `workflow_id`、`operation_id` 与可选
`input_state`。`check`、`join`、`cancel` 读取非空 `run_ids` 数组；`list` 可读取
`statuses`，允许 `pending/running/error/success/timeout/interrupted`。所有结果统一投影
为 `workflow_run_result.action/runs` 数组。每种 action 都从
`workflow_run.target_node_id` 选择下一 Canvas Node。

## 返回 contract

返回值必须是 `langgraph.types.Command`。当前允许：

- `update`: 扁平键值 mapping，直接合并进 Workflow 变量表。
- `goto`: 一个目标 Node ID、目标 Node ID sequence，或省略。

`goto` 中的每个 Node ID 必须由当前 Command 的一条 outgoing Edge 声明。Canvas End ID 会由 compiler 映射为 LangGraph `END`。省略 `goto` 时当前 path 自然结束。

Workflow 声明了 `state_schema` 时，当前 State 与 `update` 合并后的结果必须满足该 JSON Schema；不满足时本次 Run 以 `workflow.state_invalid` 失败，Command 的脚本异常与它分开报告为 `workflow.command_failed`。

当前不接受 `Send`、`resume` 或跨 graph routing。脚本不读取 Edge ID、handle 或 layout，也不返回自造 Branch/Dispatch 对象。

## 启动独立 Agent 或 Workflow

需要 AI 执行时通过 Main Agent Run facade：

```python
from langgraph.types import Command


async def command(state, runtime):
    agent_runs = runtime.context.agent_runs
    if agent_runs is None:
        raise RuntimeError("Agent Run capability is not configured")
    handle = await agent_runs.start(
        "<main-agent-uuid>",
        [{"role": "user", "content": "Review this result."}],
        operation_id="review-result",
    )
    result = await agent_runs.join(handle.thread_id, handle.run_id)
    return Command(
        update={"review": result.output},
        goto="finish",
    )
```

每次 start 创建独立 Thread/Run；显式续聊时复用 idle Thread 并创建新 Run。相同 caller Run 中的 `operation_id` 幂等，不能绑定到另一个 target。

跨 Workflow 调用使用 `runtime.context.workflow_runs.start_workflow(...)`，规则相同。child State 不会自动合并进 caller State。

## External Agent

Command Node 的 config 可绑定一个 External Agent 预设：

```json
{
  "command_id": "<command-uuid>",
  "external_agent_id": "<external-agent-uuid>"
}
```

绑定后，运行中的 `runtime.context.external_agent` 是该节点对应的 facade；未绑定时为 `None`。facade 提供 `name`、`agent_name` 和 `run(prompt, conversation=None, on_event=None)`。它启动预设描述的外部 CLI，返回包含 `status`、`response`、`conversation_id`、`denied_actions` 等字段的结果。

示例 `antigravity-agent-command` 演示完整调用：优先读取 `state.external_agent_run.prompt`，没有覆盖值时读取 Lifecycle Store 中本次请求的最后一条 `user` 消息；CLI 事件通过 `get_stream_writer()` 传给 Workflow Event Output。External Agent 的 system prompt 由预设拥有，示例不会把请求中的 `system` / `assistant` 历史压平后注入一次 CLI 提问。

## MCP

Command 通过 ordered `mcp_refs` 装配 MCP Requirement。未装配时 `runtime.context.mcp` 为 `None`；装配后可调用 `available_tools`、`call_tool`、`get_resources` 和 `get_prompt`，且只能访问当前 allowlist。

MCP facade 不暴露 Connection、secret、client 或 session。网络和文件 I/O 应使用 async API；只有无法异步化的同步资源 owner 才使用 `asyncio.to_thread()` 隔离。

## 失败边界

下列情况使当前 Workflow Run 以稳定 Command 错误失败：

- 返回值不是官方 `Command`；
- `update` 不是 mapping、包含未知 channel 或 channel 形状错误；
- `goto` 不是字符串/字符串 sequence，或目标没有对应 outgoing Edge；
- 使用 `Send`、`resume` 或跨 graph routing；
- package 物化、MCP 调用或脚本本身抛出异常。
