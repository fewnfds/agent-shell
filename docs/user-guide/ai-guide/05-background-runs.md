# 使用 background Run

background Run 是 optional capability。普通 linear Workflow、synchronous Subagent 和 Task Dispatcher 不需要它。

Agent Shell 提供 single-process background task system。该能力通过当前 Run 的官方 `Runtime.context.background_runs` 暴露给 Command Node、Task Dispatcher、Custom Tool、Middleware 和普通 Node：

```python
commands = runtime.context.background_runs
handle = await commands.start_agent(
    "<target Main Agent UUID>",
    operation_id="review:item-42",
    shared_vars={"item_id": "42"},
)
snapshots = await commands.check([handle.task_id])
snapshot = snapshots[0]
```

可用命令只有 `start_agent()`、`start_workflow()`、`check()`、`list()` 和 `cancel()`。`start_workflow()` 的 target 范围是已 enabled child Workflow；background Agent 使用自身 effective Filesystem。command 立即返回 handle，caller 自行决定如何 poll、
wait、retry、aggregate 或结束。`check()` 和 `cancel()` 都返回 snapshot 列表，其中未知 task ID 的状态为 `not_found`；`list(statuses=...)` 可按状态过滤。

`background_tasks` 是 Workflow State 的正式 channel，写入形状为 `{task_id: snapshot_dict}`。需要保存 handle 或 snapshot 时先调用 `model_dump(mode="json")`，不要把 Pydantic 对象本身写入 State。

## Lifecycle、Run 和 thread

一次外部 `/v1/chat/completions` request 创建一个 Lifecycle，并拥有一个 parent Run/thread。background invocation 会在同一 Lifecycle 中创建独立 child Run：

```text
Lifecycle
  parent Run
  background Agent Run
  background Workflow Run
```

每个 Run 都有独立的 `run_id`、`thread_id` 和 invocation identity；background child 还带 `parent_run_id`、`launcher_id`、
`background_task_id` 和 `run_depth`。这些 identity 只能从官方 `Runtime.context` 读取，不能由 script 伪造，也不能把整个 Runtime/context/commands 写进 State、Store 或 checkpoint。

Lifecycle Store 保存本次 request 的 immutable input、invocation artifact 和 task record；Workflow State 只保存 routing 所需的 lightweight reference。
独立 background Run 不自动复制或 merge parent Run 的 `messages`、State、checkpoint 或 Filesystem `files` channel。跨 Run 共享的 large artifact 通过同一 Lifecycle 的 managed Filesystem 或官方 Store route 保存，再由 child WIC/Tool 按 reference 读取。

background child 的 output 默认静默消费，不自动混入 parent OpenAI response。只有 parent 通过 `check()`/`list()` 取得事实并显式把 result 写入自己的 State、Store 或 output policy，result 才成为 parent 后续可见材料。

## operation_id 与幂等

每次启动接收当前 caller Run 内稳定的 `operation_id`。服务端先去除首尾空白，再校验长度为 1 至 128 个字符；空值或超长值返回 422 `background_operation_id_invalid`。同一 Lifecycle、同一 caller Run、同一规范化 operation ID 再次调用时返回原 task handle，不会重复 dispatch；若改用另一个 target，返回 409 `background_operation_conflict`。同一 Run 内不同 Node 也不能无意复用 operation ID，调用方应加入稳定的业务或 Node 前缀。该保证不跨 caller Run，也不跨尚未实现的 Resume；确实需要再次派遣时使用新的业务 operation ID。

background Run 不属于 canvas Agent Node。background Agent 没有 `workflow_node_id`，但有实际 `agent_id`；background Workflow 也不会出现在 parent Graph 的 Node catalog 中。Deep Agents synchronous Subagent 和 Task Dispatcher 的 request-scoped dynamic worker 是另外两种 execution semantics，
background Run system 不改变它们。

## Lifecycle Management API

Management API 只提供 Lifecycle/Run 的只读观测与 explicit cleanup，不提供从外部启动任意 background task 的 endpoint：

| 请求 | 作用 |
| --- | --- |
| `GET /api/workflow-lifecycles?page=1&page_size=10&query=` | 分页列出 Lifecycle、task status count、Run/checkpoint/Store/Filesystem summary |
| `GET /api/workflow-lifecycles/{lifecycle_id}` | 获取一个 Lifecycle 摘要 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/events` | 按 Run、Node invocation 或 event type 分页读取结构事件 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}` | 获取单个 Run 的摘要、事件与 checkpoint 计数 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/download` | 下载 Lifecycle 诊断包 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download` | 下载单个 Run 诊断包 |
| `DELETE /api/workflow-lifecycles/{lifecycle_id}` | 清理 parent/child Debug thread、Store prefix；存在 active Run/task 时返回 409 |

删除时可选 `?delete_dynamic_directories=true` 清理本 Lifecycle 的 managed dynamic directory。parent Run 到达 End 不会自动取消 background task，
也不会自动删除 Lifecycle；只有 parent 不再运行且所有 background task 均离开 `pending`、`running`、`cancel_requested` 状态后，Lifecycle 才接受 explicit delete。Lifecycle 进入 `deleting` status 后不再接受新的 background Run，
cleanup 失败时保留该 status，以便继续 cleanup。Lifecycle summary 不返回 messages、Provider secret 或 host path。

下一步：[Validation、enabled 与真实 invocation](06-validation-and-references.md)。
