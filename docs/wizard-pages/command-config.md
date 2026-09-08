# Command Node

Command Node 是在 Workflow control graph 中执行确定性 Python 的 programmable Node。它读取当前 Workflow State 和 Runtime Context，直接返回官方 `langgraph.types.Command(update=..., goto=...)`。

## Package 与入口

模板位于 `data/templates/workflow/command/<template-key>/`，内置示例位于 `examples/workflow-components/command/<example-key>/`。配置保存后拥有独立的 `python_packages/command/<configuration-name>/` 目录和 `family: workflow-node`、`adapter: command` manifest。

`main.py` 提供同步无参工厂 `create_command()`；工厂返回签名为 `async command(state, runtime)` 的 callable：

```python
from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        target = "review" if shared_vars.get("needs_review") else "finish"
        return Command(
            update={"shared_vars": {"selected_target": target}},
            goto=target,
        )

    return command
```

文件编辑在下一次物化时生效；`requirements.txt` 变化后重启 Agent Shell 以准备依赖。扩展运行在服务进程的受信任边界内，没有 sandbox。

## 输入

- `state` 是当前 State 的独立副本。现行 `WorkflowState` 只有 `shared_vars`。
- `runtime` 是 LangGraph 注入的 `Runtime[WorkflowRuntimeContext]`。
- Shell 身份从 `runtime.context` 读取，包括 Lifecycle、Workflow Run、Workflow、Command Node 和当前 Node invocation。
- 官方 Run/checkpoint/task/retry 信息从 `runtime.execution_info` 读取。
- `runtime.context.agent_runs` 与 `workflow_runs` 提供独立 Graph Run facade。
- `runtime.store` 是 Agent Server Store；只有存在明确 namespace 和 consumer 时才写入。

脚本对传入 `state` 副本的原地修改不会自动提交。所有 State 变化都必须放入返回 Command 的 `update`。

## 内置成功示例

内置 catalog 提供四个职责互补的 Command：

| 模板 | 从哪里取值 | 写入 `update.shared_vars` | `goto` 来源 |
| --- | --- | --- | --- |
| `state-routing-command` | `shared_vars.items` 与两个目标 Node ID | `item_count`、`review_item_count`、`selected_target_node_id` | 有待复核项时使用 `review_target_node_id`，否则使用 `complete_target_node_id` |
| `runtime-context-command` | `runtime.context`、`runtime.execution_info`、`shared_vars.runtime_target_node_id` | 显式 JSON-compatible `command_runtime.context/execution_info` projection | `runtime_target_node_id` |
| `agent-run-command` | `shared_vars.agent_run` 与 `runtime.context.agent_runs` | `agent_run_result` | `agent_run.target_node_id` |
| `workflow-run-command` | `shared_vars.workflow_run` 与 `runtime.context.workflow_runs` | `workflow_run_result` | `workflow_run.target_node_id` |

State routing 的成功输入例如：

```json
{
  "shared_vars": {
    "items": [
      {"id": "item-1", "requires_review": true},
      {"id": "item-2", "requires_review": false}
    ],
    "review_target_node_id": "manual-review",
    "complete_target_node_id": "publish"
  }
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
  "shared_vars": {
    "agent_run": {
      "action": "start",
      "target_node_id": "wait-for-agent",
      "main_agent_id": "<main-agent-uuid>",
      "operation_id": "review:artifact-42",
      "input": [{"role": "user", "content": "Review the artifact."}]
    }
  }
}
```

`start` 可额外传 `thread_id` 续接 idle Agent Thread。`check`、`get`、`join`、`cancel`
则读取 `thread_id` 与 `run_id`，并分别调用同名 Agent facade 方法。结果投影到
`agent_run_result.action/run`；`get` 是 `check` 的同语义入口。

Workflow Run 示例的 `start` 读取 `workflow_id`、`operation_id` 与可选
`input_shared_vars`。`check`、`join`、`cancel` 读取非空 `run_ids` 数组；`list` 可读取
`statuses`，允许 `pending/running/error/success/timeout/interrupted`。所有结果统一投影
为 `workflow_run_result.action/runs` 数组。每种 action 都从
`workflow_run.target_node_id` 选择下一 Canvas Node。

## 返回 contract

返回值必须是 `langgraph.types.Command`。当前允许：

- `update`: `WorkflowState` partial update；只允许 `shared_vars` mapping。
- `goto`: 一个目标 Node ID、目标 Node ID sequence，或省略。

`goto` 中的每个 Node ID 必须由当前 Command 的一条 outgoing Edge 声明。Canvas End ID 会由 compiler 映射为 LangGraph `END`。省略 `goto` 时当前 path 自然结束。

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
        update={"shared_vars": {"review": result.output}},
        goto="finish",
    )
```

每次 start 创建独立 Thread/Run；显式续聊时复用 idle Thread 并创建新 Run。相同 caller Run 中的 `operation_id` 幂等，不能绑定到另一个 target。

跨 Workflow 调用使用 `runtime.context.workflow_runs.start_workflow(...)`，规则相同。child State 不会自动合并进 caller State。

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
