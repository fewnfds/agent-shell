# 任务分发

任务分发是 Workflow 画布上的动态 map 节点。它从当前 Workflow State/Runtime Context 生成运行时数量的任务，Shell 使用
LangGraph 官方 `Send` 把任务发给一个或多个 Agent Node。画布只保存一个 Task Dispatcher Node 和候选 Dispatch Edge，
不会为每条运行时任务持久化临时 Node。

## 从内置示例创建

1. 打开【Workflow 组件 / 任务分发】，新建配置。
2. 选择 `内置示例-item-list-dispatcher` 并保存。
3. 按实际 State 结构修改当前配置独占的 `main.py`。
4. 在 Workflow 画布加入 Task Dispatcher，选择该配置。
5. 建立 `dispatch_key=item` 到目标 Agent 的 Dispatch Edge。

示例读取：

```python
state["shared_vars"] = {
    "items": [{"id": "item-1", "value": 42}],
}
```

并为每个 item 生成一个任务。字段和来源只是示例，Dispatcher 可以按场景读取完整 State、Runtime Context 或 Store。
源码位于 `examples/workflow-components/task-dispatcher/item-list-dispatcher/`。

## Package 与入口

用户模板位于 `data/templates/workflow/task_dispatcher/<template-key>/`；首次保存后复制为
`data/configuration-repositories/<repository-uuid>/python_package_instances/task-dispatcher/<configuration-uuid>/`。manifest 固定使用 `family: workflow-node`、
`adapter: task-dispatcher`。`main.py` 必须提供同步工厂：

```python
def create_dispatcher():
    async def dispatch(state, runtime):
        # Example source only; select any relevant State/Runtime/Store data.
        items = state.get("shared_vars", {}).get("items", [])
        return {
            "tasks": [
                {
                    "task_id": f"item:{item['id']}",
                    "dispatch_key": "item",
                    "payload": {"item": item},
                }
                for item in items
            ],
            "update": {"shared_vars": {"dispatched_count": len(items)}},
        }

    return dispatch
```

- `state` 是 detached 可变副本；`runtime` 是 LangGraph 注入的官方 `Runtime[WorkflowRuntimeContext]`。Lifecycle Store 使用
  `runtime.store`，后台 Run 命令使用 `runtime.context.background_runs`。不要把 Runtime 或 commands 写入 State/Store/checkpoint。
- 示例中的 `shared_vars.items` 不是固定来源；可以按当前 Workflow 从完整 State、Runtime Context 或 Store 选择任务材料。
- `tasks` 必须至少有 1 项，当前不设置产品数量上限；同一次调用中的 `task_id` 唯一，并应来自稳定业务身份。
- `dispatch_key` 必须与同源 Dispatch Edge 完全一致；同一个 key 只能连接一个目标。
- `payload` 必须是严格 JSON 对象，不能包含 Python 对象或 `NaN`、`Infinity` 等非有限数；worker 所需的本批数据都应放在这里。
- `update` 可以更新任意已声明 Workflow State channel，但每个值必须符合该 channel 的现有类型；它只更新父 State，
  不隐式改写本批显式 Send State。
- 包不 import LangGraph，不返回 Node ID、`Send` 或 `Command`。

没有任务时，第一阶段要求由上游 Command Node 绕过 Dispatcher；返回空 `tasks` 会使运行失败。

## Worker 如何读取任务

Shell 为每项任务补充 `dispatcher_node_id` 与 `dispatcher_invocation_id`，形成 `WorkflowTaskContext`。目标 Agent 子图及其
Middleware 从私有 State 读取：

```python
task_from_state = state["workflow_task"]
```

worker 完成后，父 Workflow State 的 `agent_invocations` 轻量记录带不含 payload 的 `workflow_task` identity，因此下游启用
`defer=True` 的汇总 Agent 可以等待 pending worker 完成，再按 `(dispatcher_node_id, task_id)` 选择结果；完整 task payload
和 messages 通过 `result_ref` 从 Store 读取。

WIC 可以把 payload 编排进当前 worker 的私有 `messages`，但不负责任务认领或共享锁。任务并发由 LangGraph 调度，当前
Workflow 设置有限的 `max_concurrency`，任一 worker 未处理的异常会使本次运行 fail-fast。

这些 Python 代码运行在服务进程的受信任边界内，没有 sandbox。源码在下一次 Workflow 请求重新加载；
`requirements.txt` 修改后需要重启 Agent Shell。
