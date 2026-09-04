# Command Node

Command Node 是 Workflow canvas 上执行确定性 Python 的 programmable Node。一次调用可以更新 Workflow State、通过 Branch Edge 激活零个或多个 successor，并通过 Dispatch Edge 为 Agent Node 创建零个或多个独立任务。

## Package 与入口

用户模板位于 `data/templates/workflow/command/<template-key>/`，内置示例位于 `examples/workflow-components/command/<example-key>/`。新配置首次保存时复制到 `data/config_repos/<repository-name>/python_packages/command/<configuration-name>/`，并生成 `family: workflow-node`、`adapter: command` 的 `package.json`。

`main.py` 提供同步无参工厂 `create_command()`。工厂返回的 async callable 签名必须恰为 `(state, runtime)`：

```python
def create_command():
    async def command(state, runtime):
        items = state.get("shared_vars", {}).get("items", [])
        return {
            "activate": ["audit"] if items else [],
            "dispatch": [
                {
                    "task_id": f"item:{item['id']}",
                    "dispatch_key": "process",
                    "payload": {"item": item},
                }
                for item in items
            ],
            "update": {"shared_vars": {"planned": len(items)}},
        }

    return command
```

每个 Command 配置拥有独立 Python 扩展目录。文件编辑立即作用于该配置；`requirements.txt` 变化需要重启 Agent Shell 以重新准备依赖。完整目录、manifest、imports 和 dependency contract 见[文件化 Python 扩展包](../user-guide/middleware-packages.md)。

## 输入

- `state` 是当前 Workflow State 的独立可变副本，包含本次调用实际存在的 `shared_vars`、`agent_invocations` 和 `files`；
- `runtime` 是 LangGraph 注入的 `Runtime[WorkflowRuntimeContext]`。当前 Shell Lifecycle、Workflow Run、Workflow 和 Node invocation scope 使用 `lifecycle_id`、`run_id`、`caller_run_id`、`operation_id`、`workflow_id`、`workflow_node_id`、`agent_profile_id` 与 `node_invocation_id` 等明确字段，Store 位于 `runtime.store`，跨 Workflow Run 命令位于 `runtime.context.workflow_runs`；LangGraph 的 thread、run、checkpoint、task 和 retry/attempt 信息直接读取 `runtime.execution_info`；
- 脚本可以修改 `state` 副本，也可以显式返回 `update`。mutation delta 与 `update` 合并时，显式 `update` 覆盖同名顶层 channel。

## MCP

Command 配置通过 ordered `mcp_refs` 装配零个或多个 MCP Requirement。未装配时 `runtime.context.mcp` 为 `None`；装配后得到只属于当前 Command 的窄 facade，不暴露 MCP Connection、secret、client 或 session。

```python
async def command(state, runtime):
    mcp = runtime.context.mcp
    if mcp is None:
        return {"update": {}}
    result = await mcp.call_tool(
        "browser",
        "navigate",
        {"url": "https://example.com"},
    )
    if result.status == "error":
        raise RuntimeError(str(result.content))
    return {"update": {"shared_vars": {"browser_result": result.content}}}
```

`available_tools()` 返回 `namespace -> raw Tool names`；`call_tool(namespace, tool_name, arguments)` 只能调用当前 Command allowlist 内的 Tool，并返回带 `success|error` status 的 LangChain `ToolMessage`。`get_resources(namespace, uris=...)` 与 `get_prompt(namespace, prompt_name, arguments=...)` 要求该 namespace 已装配，并保留 LangChain MCP adapter 的返回对象。完整连接、映射和 secret 说明见 [MCP 连接、映射与调用](../user-guide/mcp.md)。

## 返回 contract

返回对象包含三个可独立省略的字段：

- `activate: list[str]`：需要激活的 Branch Edge key；
- `dispatch: list[object]`：需要创建的 Agent 任务；
- `update: dict[str, object]`：Workflow State partial update。

三个字段默认分别为空列表、空列表和空映射。一次调用可以同时返回 Branch、Dispatch 和 State update。空 `activate` 与空 `dispatch` 会只提交 `update`，当前 path 在 Command 处自然结束。

### Branch Edge

Command 的 `branch` output handle 连接 Branch Edge。每条 Edge 保存一个大小写敏感的 `branch_key`，去除首尾空白后长度为 1 至 64 个字符；同一个 Command 来源中的 key 必须唯一。`activate` 中每个 key 必须存在匹配 Edge，同一次返回中不能重复。

compiler 把 Branch target Node ID 直接交给官方 `Command.goto`。Branch Edge 只声明候选 target，不注册静态 `add_edge`，所以未被选择的 Branch 不会运行。

### Dispatch Edge

Command 的 `dispatch` output handle 只能连接 Agent Node input。每条 Dispatch Edge 保存唯一 `dispatch_key`。一个 Dispatch Edge 可以把同一个 Agent Node 激活任意多次；重复次数来自返回的 task 数量，不通过画布创建平行 Edge 表达。

每个 dispatch item 的格式是：

```json
{
  "task_id": "item:42",
  "dispatch_key": "process",
  "payload": {"item_id": 42}
}
```

- `task_id` 去除首尾空白后长度为 1 至 128 个字符，并在本次 Command invocation 内唯一；稳定业务身份便于 downstream aggregation 选择结果；
- `dispatch_key` 必须匹配当前 Command 的一条 Dispatch Edge；
- `payload` 必须是严格 JSON object，拒绝任意 Python object 和 `NaN`、正负无穷等非有限数；
- task 列表可以为空，不设置数量、payload 大小、并发数或超时的 Command 专属上限。

compiler 为每项构造 `workflow_task`，复制调用前的 Workflow State snapshot，并创建官方 `Send(target_agent_node_id, task_state)`。同一批 `update` 不自动进入这些 `Send` 的 State；需要成为 worker input 的值应直接写入 task `payload`。

Agent 的 private State 可以读取：

```json
{
  "command_node_id": "plan",
  "command_invocation_id": "<LangGraph task identity>",
  "task_id": "item:42",
  "dispatch_key": "process",
  "payload": {"item_id": 42}
}
```

完整 task 与 Agent messages 写入 Lifecycle Store artifact。Workflow State 的 `agent_invocations` 只保存不含 payload 的 task identity 和 `result_ref`。需要等待动态 worker 全部完成的 aggregation Agent 使用 `defer=true`，再按 `(command_node_id, task_id)` 选择结果。

## Edge 与 target identity

画布 target identity 是 Node ID。两个 Agent Node 即使引用同一个 Main Agent 配置 UUID，也代表两个独立 target 和 invocation。任意一个有向 `source Node ID -> target Node ID` 组合只能存在一条 Edge，不因 handle、Edge type、branch key 或 dispatch key 而放宽；反向连接是另一个有向组合。

Branch key 与 Dispatch key 各自在同一个 Command source 内唯一。Dispatch target 只接受 Dispatch incoming Edge，不能同时接收 Normal 或 Branch incoming Edge。

## 失败边界

未知或重复 key、重复 `task_id`、非法 payload、未声明 State channel、channel value 形状错误、无效返回对象和脚本 exception 都会让 current Workflow Run 以受控 Command 错误失败。package 不读取 Edge ID、target Node ID 或画布布局，也不直接返回 LangGraph `Command`/`Send`；这些对象由 compiler 根据已校验 Graph 机械构造。
