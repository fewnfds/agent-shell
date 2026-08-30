# 使用 background Run

本章说明 independent child Workflow Run 的启动、State isolation、检查、取消和 result handoff。

background Run 为 child 创建独立 `run_id`、Workflow State 和终态。async Node、parallel Node、synchronous Subagent 和 Command dispatch worker 在 current Run 内完成。

## 1. 选择条件

Normal Edge 激活设计时已知的固定 successor，执行仍属于 current Run。

synchronous Subagent 由 Main Agent model 委派给 specialist，并在取得结果后继续同一个 Agent loop。

Command 根据运行时数据生成 Agent worker task，这些 worker 属于 current Workflow Run。

background Run 的 child 拥有独立 `run_id`、Workflow State 和终态；launcher 在 start 后立即取得 handle，并自行决定 check、cancel、继续其他逻辑或结束自己的 path。

## 2. 准备 child Workflow

background target 必须是当前 request 配置快照中已经 enabled 的 child Workflow UUID。

需要后台执行一个 Main Agent 时，创建 child Workflow：

```text
Start -> Agent -> End
```

child Workflow 使用自己的 metadata：

- 自己的 `checkpointer_id`；
- 自己的 runtime limit；
- 自己的 `cancel_on_upstream_termination`；
- 自己的 Graph 和 Component reference。

parent 和 child 是否启用 Checkpointer 互不继承。只有引用 Checkpointer 的 Run 才拥有 `checkpoint_thread_id`。

publish child 后确认 `enabled=true`。child 不出现在 `/v1/models`，但可以作为 background target。

## 3. Controller topology

需要等待或处理 child 结果的 parent 可以使用：

```text
Start child
  -> persist handle
  -> check
  -> business decision
  -> optional cancel or finalize
  -> End
```

Controller 数据按以下 ownership 保存：

- `shared_vars.background_controller` 保存 phase、pending task ID、winner 和 artifact reference；
- `background_tasks` 保存最新 task handle 或 snapshot；
- child 完整业务 artifact 写入 child 可访问的 Store 或 mapped Filesystem；
- parent 通过明确 reference 读取需要的 artifact。

controller State 示例：

```json
{
  "shared_vars": {
    "background_controller": {
      "phase": "poll",
      "task_ids": [
        "task-a"
      ],
      "pending_ids": [
        "task-a"
      ],
      "result_ref": null
    }
  },
  "background_tasks": {
    "task-a": {
      "task_id": "task-a",
      "runtime_status": "running"
    }
  }
}
```

fire-and-forget 是允许的，但 design record 必须明确 parent 结束后 child 继续运行，并保留 task identity 供 Lifecycle observability 使用。

## 4. Runtime command

background command 通过 current invocation 的 Runtime Context 暴露：

```python
commands = runtime.context.background_runs

handle = await commands.start_workflow(
    "<enabled child Workflow UUID>",
    operation_id="review:item-42",
    shared_vars={
        "item_id": "42"
    }
)

snapshots = await commands.check([handle.task_id])
snapshot = snapshots[0]
```

可用 command 只有：

- `start_workflow()` 启动 enabled child Workflow，并立即返回 handle；
- `check(task_ids)` 读取指定 task 的当前 snapshot，不等待完成；
- `list(statuses=...)` 列出当前 Lifecycle 中的 task，可按状态过滤；
- `cancel(task_ids)` 请求取消指定 task，并返回 snapshot。

Custom Tool 使用 `ToolRuntime.context.background_runs`。Middleware 根据 hook 形状使用 `runtime.context.background_runs` 或 `request.runtime.context.background_runs`。

可以向 `start_workflow()` 传递 initial `shared_vars` 和可选 `workflow_task`。输入在 dispatch 时深拷贝，不与 parent State 保持可变引用。

当前没有 wait、wakeup、update、delay 或自动 retry command。轮询、回边、sleep、retry 和 exit condition 由用户 Graph 明确表达。

## 5. 保存 handle 和 snapshot

`background_tasks` 是 Workflow State 的正式 channel。写入前把 Pydantic object 转为普通 JSON dict：

```python
handle_payload = handle.model_dump(mode="json")
snapshot_payload = snapshot.model_dump(mode="json")
```

Command 返回示例：

```python
return {
    "activate": ["poll"],
    "update": {
        "background_tasks": {
            handle.task_id: handle_payload
        },
        "shared_vars": {
            "background_controller": next_controller
        }
    }
}
```

finalizer 只处理 current Workflow 启动并记录的 task ID。不要扫描和取消整个 Lifecycle 中不属于当前 controller 的 task。

## 6. `operation_id`

每次 start 必须提供稳定 `operation_id`。

系统约束：

- service 去除首尾空白；
- 规范化后长度必须是 1 至 128 个字符；
- 同一 Lifecycle、同一 caller Run、同一 operation ID 再次调用时返回原 handle，不重复 dispatch；
- 同一 operation ID 改用另一个 target 时返回 409 `background_operation_conflict`；
- 幂等范围不跨新的 caller Run。

建议加入稳定的 Node 或业务前缀：

```text
review:item-42
publish:document-17
controller-a:batch-2026-08-26
```

不要使用当前时间或随机值破坏 retry 时的幂等，除非业务明确要求每次启动新任务。

## 7. Status 和检查逻辑

task snapshot 的 `runtime_status` 可能是：

- `pending`；
- `running`；
- `cancel_requested`；
- `succeeded`；
- `failed`；
- `cancelled`；
- `interrupted`；
- `not_found`。

`not_found` 表示指定 task ID 未知。旧 service instance 遗留的 active record，或者当前 instance 已无 live task 的 active record，可以在读取时归一为 `interrupted`。

一次 poll 可以执行：

1. 从 controller 读取待检查 ID；
2. 调用一次 `check()`；
3. 保存 snapshot；
4. 根据业务终态更新 controller；
5. 选择继续 poll、处理 artifact、进入 failure 或 finalizer。

如果 async Node 中使用 `await asyncio.sleep(...)` 放缓轮询，等待会占用 current Node invocation 时间，并受 parent `execution_timeout_seconds` 约束。

## 8. Lifecycle、Run 和 State isolation

一次外部 `/v1/chat/completions` request 创建一个 Lifecycle 和 parent Run。background invocation 在同一 Lifecycle 中创建 independent child Run：

```text
Lifecycle
  parent Run
  background child Workflow Run
```

child 拥有独立：

- `run_id`；
- Workflow State；
- 可空 `checkpoint_thread_id`；
- `parent_run_id`；
- `launcher_id`；
- `background_task_id`；
- `run_depth`。

child 不自动复制或 merge parent 的 request messages、State、checkpoint 或 StateBackend `files` channel。

同一 Lifecycle 中需要共享大型 artifact 时，让 parent 和 child 引用同一个 configured mapped Filesystem route，或者使用明确的 Store route。State 和 task payload 只保存 reference。

## 9. Output 和 result handoff

background child 使用自己的 Agent Event Output 和 Workflow Event Output。公开 response 保持开放时，child 已投影的事件与 parent 事件一起进入同一个 Lifecycle Response Stream Scheduler；scheduler 明确识别 Parent 与各 child Run identity，当前按现有 atom 策略和事件到达先后排队，对所有 role 使用相同调度权重。后续角色权重策略可以建立在该身份边界上。

`check()` 或 `list()` 返回 task status 和受限系统结果，不会把 child 完整 Agent output 变成 parent prompt，也不保存公开事件文本。parent 到达 End 并封口 response 后，仍在运行的 independent child 继续维护自己的终态、usage、Debug 和诊断，但后续事件没有可写入的公开 response。要求交付完整 child 事件时，controller 必须在 parent End 前等待对应 task terminal。

child 需要交付业务结果时：

1. child 把 artifact 写入约定的 Store 或 mapped Filesystem；
2. child 或 controller 保存稳定 `result_ref`；
3. parent 取得 task terminal status；
4. parent 按 reference 读取 artifact；
5. parent 显式写入自己的 State、Agent input 或 output policy。

## 10. Upstream termination

child Workflow 的 `cancel_on_upstream_termination` 默认 `true`。

launcher Run 取消或失败时，仍 active 且开关为 `true` 的直接 child 会被取消。child 的取消继续按各自配置向下一层传播。

launcher 正常到达 End 不触发 child 取消。

开关为 `false` 时，child 保持 independent Run，直到自己完成、失败、被显式取消或应用 shutdown。

如果 parent 成功后不应留下 child，必须在 Graph 中设计 finalizer；不要假定 End 会清理 task。

## 11. Lifecycle Management API

Management API 只负责 observability 和 explicit cleanup，不提供从外部任意启动 background task 的 endpoint。

常用 endpoint：

- `GET /api/workflow-lifecycles` 分页列出 Lifecycle 和摘要；
- `GET /api/workflow-lifecycles/{lifecycle_id}` 读取一个 Lifecycle 摘要；
- `GET /api/workflow-lifecycles/{lifecycle_id}/events` 读取结构事件；
- `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}` 读取 Run 摘要；
- `GET /api/workflow-lifecycles/{lifecycle_id}/download` 下载 Lifecycle 完整运行详情 ZIP；
- `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download` 下载单个 Run 详情 ZIP；
- `DELETE /api/workflow-lifecycles/{lifecycle_id}` 显式清理一个 terminal Lifecycle；
- `POST /api/workflow-lifecycles/delete` 按 query 清理匹配的 terminal Lifecycle。

存在 active Run 或 task 时，单项删除返回 409。Lifecycle 没有定时 retention，正常 End 不自动删除。

Lifecycle summary 不返回 messages、Provider secret 或 resolved host path。download 属于 management-only 运行详情，按安全与部署边界处理。

详细观测说明见[Runtime observability](../runtime-observability.md)。

## 12. 本章完成结果

进入最终 validation 前确认：

- child 的独立 Run、State 与终态符合目标 topology；
- target 是当前 Repository 中 enabled child Workflow UUID；
- child input 通过 initial State、workflow task 或 artifact reference 明确传递；
- `operation_id` 稳定，并在 current caller Run 内唯一；
- handle 和 snapshot 已序列化后写入 `background_tasks`；
- controller 只保存轻量业务状态和 artifact reference；
- polling、sleep、retry 和 exit condition 已在 Graph 中显式表达；
- child 公开事件已进入 Lifecycle scheduler，持久业务结果仍使用明确的 result/artifact handoff；
- upstream termination 配置符合业务；
- finalizer 只处理当前 controller 拥有的 task；
- parent 正常完成时不会意外遗留 active child。

下一步阅读[验证、运行与交付](08-validate-run-deliver.md)。
