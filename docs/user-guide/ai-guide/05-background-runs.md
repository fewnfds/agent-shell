# 使用 background Run

background Run 是 optional capability。普通 linear Workflow、synchronous Subagent 和 Task Dispatcher 不需要它。

## 1. 先判断是否需要 independent child Run

| 机制 | execution scope | caller 是否等待 | 适用场景 |
| --- | --- | --- | --- |
| Normal Edge | current parent Graph | 等待当前 Super-step，再激活固定 successor Node | statically known sequential/parallel Node |
| synchronous Subagent | current Main Agent invocation | Main Agent 等待 Subagent 返回后继续 Agent loop | 模型决定委派给一个 specialist |
| Task Dispatcher worker | current Workflow Run 的动态 Graph task | current Graph 调度并等待其任务语义完成 | 运行时才知道数量和 payload 的 Agent map |
| background Run | 同一 Lifecycle 中的 independent child Workflow Run/State；可按自身配置拥有 Checkpoint | start 立即返回；parent Run 自己决定是否检查、等待或取消 | detached execution、长任务、independent child Workflow |

如果调用方需要 child 完成后立即继续当前逻辑，优先使用 Edge、Subagent 或 Task Dispatcher。需要独立 execution identity，或 parent 必须在 child 仍运行时继续其他工作时，再选择 background Run。

## 2. Controller 流程

一个可控的 parent 通常包含以下步骤：

```text
start child
  -> persist handle
  -> poll / check
  -> business decision
  -> optional cancel / finalize
  -> End
```

建议把业务 phase、pending task ID、winner 和 result reference 放入 `shared_vars.background_controller`，把最新 task snapshot 放入 `background_tasks`。完整建议结构见[Workflow 编排总则：Background Run controller](00-workflow-orchestration-principles.md#35-background-run-controller)。

每一步的职责可以保持单一：

1. **start Node**：使用稳定 `operation_id` 启动 child，并持久化 handle；
2. **poll Node**：只对已记录的 task ID 调用 `check()`，保存最新 snapshot；
3. **decision Node**：根据业务终态选择继续 poll、处理结果或进入 failure path；
4. **finalizer Node**：按业务需要取消冗余 child，确认 task 已进入终态；
5. **End**：controller 已达到明确完成状态后结束 parent path。

parent 可以选择 fire-and-forget，此时应在业务设计中明确 child 继续运行，并保留 task identity 供 Lifecycle observability 使用。

## 3. Background command API

Agent Shell 提供 single-process background task system。该能力通过 current Run 的官方 `Runtime.context.background_runs` 暴露给 Command Node、Task Dispatcher、Custom Tool、Middleware 和 executable Node：

```python
commands = runtime.context.background_runs
handle = await commands.start_workflow(
    "<enabled child Workflow UUID>",
    operation_id="review:item-42",
    shared_vars={"item_id": "42"},
)
snapshots = await commands.check([handle.task_id])
snapshot = snapshots[0]
```

可用命令只有 `start_workflow()`、`check()`、`list()` 和 `cancel()`。target 范围是已 enabled child Workflow；需要执行一个 Main Agent 时，创建 `Start -> Agent -> End` child Workflow。`start_workflow()` 立即返回 handle，caller 自行决定如何 poll、wait、retry、aggregate 或结束。`check()` 和 `cancel()` 都返回 snapshot 列表，其中未知 task ID 的状态为 `not_found`；`list(statuses=...)` 可按状态过滤。

child Workflow 的【父运行取消或失败时终止】默认开启。launcher Run 被取消或失败时，仍 active 的 child 会被取消，并继续向它自己的 children 传播；launcher 正常到达 End 不触发。关闭后 child 保持 independent Run，直到自己完成、失败、被显式 `cancel()` 或应用关闭。

当前 background command API 没有 wait、wakeup、update 或 delay command。轮询间隔、回边、重试和唤醒条件由用户 Graph 逻辑表达。需要放缓短轮询时，可以在 async Node callable 中使用 `await asyncio.sleep(...)`；等待会占用 current Node invocation 时间，并受 parent Workflow 的 `execution_timeout_seconds` 约束。

`background_tasks` 是 Workflow State 的正式 channel，写入形状为 `{task_id: snapshot_dict}`。保存 handle 或 snapshot 时先调用 `model_dump(mode="json")`，再把得到的普通 dict 写入 State。

## 4. Lifecycle、Run 和可选 Checkpoint Thread

一次外部 `/v1/chat/completions` request 创建一个 Lifecycle 和 parent Run。background invocation 会在同一 Lifecycle 中创建 independent child Run：

```text
Lifecycle
  parent Run
  background Workflow Run
```

每个 Run 都有独立的 `run_id` 和 invocation identity；background child 还带 `parent_run_id`、`launcher_id`、`background_task_id` 和 `run_depth`。只有引用检查点保存器的 Workflow Run 才有 `checkpoint_thread_id`；parent 与 child Workflow 分别读取自己的 `checkpointer_id`，四种启用组合都不改变调度、状态查询或结果获取。这些 identity 从官方 `Runtime.context` 读取；State 与 Store 保存各自职责内的序列化字段，Checkpoint 只保存启用 Run 的 Graph State 快照。

Lifecycle Store 保存本次 request 的 immutable input、invocation artifact 和 task record；Workflow State 只保存 routing 所需的 lightweight reference。独立 background Run 不自动复制或 merge parent Run 的 `messages`、State、checkpoint 或 Filesystem `files` channel。跨 Run 共享的 large artifact 通过同一 Lifecycle 的 managed Filesystem 或官方 Store route 保存，再由 child AAP/Tool 按 reference 读取。

background child 的 output 默认静默消费，不自动混入 parent OpenAI response。只有 parent 通过 `check()`/`list()` 取得事实并显式把 result 写入自己的 State、Store 或 output policy，result 才成为 parent 后续可见材料。

## 5. `operation_id` 与幂等

每次启动接收 current caller Run 内稳定的 `operation_id`。服务端先去除首尾空白，再校验长度为 1 至 128 个字符；空值或超长值返回 422 `background_operation_id_invalid`。同一 Lifecycle、同一 caller Run、同一规范化 operation ID 再次调用时返回原 task handle，不会重复 dispatch；若改用另一个 target，返回 409 `background_operation_conflict`。同一 Run 内不同 Node 也不能无意复用 operation ID，调用方应加入稳定的业务或 Node 前缀。幂等范围限于 current caller Run；新的 caller Run 需要根据业务决定复用还是生成新的 operation identity。

background Run 由应用级 Manager 管理，并由自己的 Workflow 配置标识。Deep Agents synchronous Subagent 和 Task Dispatcher 的 request-scoped dynamic worker 使用各自的 execution semantics，background Run system 不改变它们。

## 6. Lifecycle Management API

Management API 只提供 Lifecycle/Run 的只读观测与 explicit cleanup，不提供从外部启动任意 background task 的 endpoint：

| 请求 | 作用 |
| --- | --- |
| `GET /api/workflow-lifecycles?page=1&page_size=10&query=` | 分页列出 Lifecycle、task status count、Run/checkpoint/Store/Filesystem summary |
| `GET /api/workflow-lifecycles/{lifecycle_id}` | 获取一个 Lifecycle 摘要 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/events` | 按 Run、Node invocation 或 event type 分页读取结构事件 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}` | 获取单个 Run 的摘要、事件与 checkpoint 计数 |
| `GET /api/workflow-lifecycles/{lifecycle_id}/download` | 下载 Lifecycle 完整运行详情 ZIP |
| `GET /api/workflow-lifecycles/{lifecycle_id}/runs/{run_id}/download` | 下载单个 Run 完整运行详情 ZIP |
| `DELETE /api/workflow-lifecycles/{lifecycle_id}` | 清理全部非空 Checkpoint Thread 和 Store prefix；存在 active Run/task 时返回 409 |

删除时可选 `?delete_dynamic_directories=true` 清理本 Lifecycle 的 managed dynamic directory。parent Run 正常到达 End 不会自动取消 background task；parent 取消或失败时按 child 的【父运行取消或失败时终止】配置传播。Lifecycle 保留到显式删除；parent 和所有 background task 进入终态后，Lifecycle 接受 explicit delete。Lifecycle 进入 `deleting` status 后冻结 background Run 创建，cleanup 失败时保留该 status，以便继续 cleanup。Lifecycle summary 不返回 messages、Provider secret 或 host path。

## 7. Background Run 完成检查

- 该 task 确实需要 independent child Run/State；需要 Checkpoint 时，目标 child Workflow 已显式选择检查点保存器；
- enabled child Workflow UUID 来自 current Configuration Repository；单 Agent 后台任务使用 `Start -> Agent -> End`；
- `operation_id` 由 stable business identity 构成，在 current caller Run 内唯一；
- start 返回的 handle 已序列化并写入 `background_tasks`；
- parent controller 只保存轻量业务状态和 artifact reference；
- polling、retry、sleep 和 exit condition 已在 Graph 中显式表达；
- parent 已通过 `check()` / `list()` 获取需要的 child 事实；
- child output 默认静默这一点已纳入 result handoff；
- child 的【父运行取消或失败时终止】是否符合独立运行需求；
- 需要收尾时，finalizer 只处理 current Workflow 启动并记录的 task ID；
- 完成 parent 时没有意外遗留的 active task。

下一步：[Validation、publish 与真实 invocation](06-validation-and-references.md)。
