# 跨 Workflow Run 调用

本章说明一个 Workflow Run 如何启动、查询、等待和取消另一个能力相同的 Workflow Run，以及 State isolation、取消传播和结果收集。

Agent Shell 的 Workflow 是人类编辑和持久化的产品定义，运行时编译为 LangGraph Graph。Assistant 是 Graph 加配置后的官方执行入口；Thread 保存该执行上下文的持久化 State；Run 是对 Assistant/Graph 的一次调用。Workflow 没有静态运行角色。

## 1. 何时创建另一个 Run

使用 current Run 内的普通 Node、异步 Python、Command dispatch 或 synchronous Subagent，当工作仍属于同一张 Graph、同一份 Workflow State 和同一个 Run。

在以下条件下使用跨 Workflow Run 调用：

- 工作需要独立 Thread、`run_id`、Workflow State 和终态；
- caller 需要在被调用 Run 仍运行时继续其他步骤；
- caller 需要显式查询、等待或取消该 Run；
- 被调用工作已经由另一个 enabled Workflow 表达。

每次调用都创建独立官方 Thread 和 Run。被调用 Workflow 可以继续调用其他 enabled Workflow，因此 A → B → C 使用同一套规则逐层形成动态 caller/spawned 关系。

## 2. 准备目标 Workflow

目标必须存在于本次请求已经冻结的 Configuration Repository 快照中，并且 `enabled=true`。所有 enabled Workflow 同时具备两种能力：作为请求入口出现在 `/v1/models`，以及被另一个 Run 调用。

需要运行单个 Main Agent 时，可以创建：

```text
Start -> Agent -> End
```

目标 Workflow 使用自己的 Graph、Agent/Component 引用、`recursion_limit`、`execution_timeout_seconds`、`max_concurrency`、事件输出和 `cancel_on_caller_termination`。caller 的 Workflow 配置不会覆盖它。

## 3. Runtime command

Agent Shell 在每个 Workflow Node invocation 的 `Runtime.context` 中注入 run-scoped `workflow_runs` facade。Command Node、Custom Tool、Middleware 或 executable Node 可以调用：

```python
handle = await runtime.context.workflow_runs.start_workflow(
    "<enabled Workflow UUID>",
    operation_id="research:market:2026-09-04",
    shared_vars={"topic": "market"},
)

snapshots = await runtime.context.workflow_runs.check([handle.run_id])
finished = await runtime.context.workflow_runs.join([handle.run_id])
active = await runtime.context.workflow_runs.list(
    statuses=frozenset({"pending", "running"})
)
cancelled = await runtime.context.workflow_runs.cancel([handle.run_id])
```

各命令的作用：

- `start_workflow()` 创建或复用当前 operation 对应的官方 Assistant/Thread/Run，并立即返回 handle；
- `check()` 通过公共 Run API 读取指定 Run；终态 Run 同时返回官方 Thread 的 current State values；
- `list()` 列出 current caller 直接启动的 Run，可按官方状态筛选；
- `join()` 通过公共 Run join API 等待指定 Run 到达终态，并返回输出；
- `cancel()` 通过公共 Run cancel API 主动取消并等待到官方终态。

Handle 包含：

```text
operation_id
workflow_id
assistant_id
thread_id
run_id
status
```

Snapshot 包含上述身份、`caller_run_id`、`workflow_name`、官方 `status`，以及可空 `output`。官方状态为：

```text
pending | running | error | success | timeout | interrupted
```

请求不存在于 current caller 的直接调用集合时，`check()`、`join()` 或 `cancel()` 返回 `status=not_found`，不会越过调用边界操作其他 Run。

## 4. `operation_id`

`operation_id` 是 current caller Run 内一次业务调用的稳定身份。去除首尾空白后不能为空。

同一 caller Run 因 Node retry 或循环再次使用相同 operation ID 且目标 Workflow 相同时，返回已经创建的官方 Run，不会重复启动。相同 operation ID 指向不同 Workflow 时返回 `409 workflow_run_operation_conflict`。确实需要再次执行同一业务目标时使用新的 operation ID。

operation ID 应来自业务 identity，例如 `research:<topic-id>` 或 `map:<item-id>:<attempt>`。不要使用列表位置、当前时间或随机值掩盖本应幂等的 retry。

## 5. 输入与 State isolation

`start_workflow()` 接受 initial `shared_vars` 和可选 `workflow_task`。输入在创建时深拷贝，不与 caller State 保持可变引用。

被调用 Run 拥有独立：

- Assistant、Thread 与 Run identity；
- Workflow State；
- Graph execution 与终态；
- 事件投影和运行配置。

它不会自动复制或 merge caller 的 State、Agent 私有 `messages` 或 `files` channel。需要共享大型 artifact 时，让两个 Run 使用约定的 Store namespace 或 mapped Filesystem route，并只在 State 中传递稳定 reference。

## 6. 保存控制状态

Workflow root State 只有 `shared_vars`、`agent_invocations` 和 `files` 三个正式 channel，没有跨 Run task 状态 channel。

后续 Node 需要继续操作某个 Run 时，只把必要的 `run_id` 和业务控制信息写入 caller 拥有的 `shared_vars`：

```json
{
  "shared_vars": {
    "research_call": {
      "run_id": "<official Run ID>",
      "phase": "waiting"
    }
  }
}
```

不要把官方 status、时间、错误或整份 Thread State 持续复制到 Workflow State。需要事实时重新调用 `check()`、`list()` 或 `join()`。

## 7. 等待和业务循环

需要完整结果时优先使用 `join()`。caller 还要执行其他工作或根据多个 Run 状态作业务决策时使用 `check()` 或 `list()`。

轮询循环必须有业务退出条件，例如全部 terminal、达到业务 deadline、已有 winner 或用户取消。`execution_timeout_seconds` 和 `recursion_limit` 是运行失败边界，不代替正常退出条件。

同时启动多个 Workflow Run 是正常用法。每个调用使用独立 Thread，因此可以并行运行；实际吞吐受用户配置的 Worker 并发和宿主资源影响。Agent Shell 不额外设置隐藏的 Run 数量上限。

## 8. 输出收集

公开 response 尚未封口时，被调用 Run 的 Agent/Workflow Event Output 会进入同一个 Lifecycle Response Scheduler，与请求入口 Run 的已投影文本共同排队。每个 Run 仍使用自己的 Event Output 配置；scheduler 按 Run identity 隔离输出 transaction。

`join()` 返回官方 Run 输出，`check()` 在 Run 已终态时返回官方 Thread current State values。调用方可以把其中需要的轻量业务结果显式合并进自己的 State、Agent input 或最终输出。

大型正文、数据集和二进制结果继续写入 Store 或 mapped Filesystem，并在 Run output 中交付 reference。这样可以避免在多个 State 中复制同一份持久数据。

如果 caller 在公开 response 封口前没有等待被调用 Run，后者可以继续执行，但之后产生的文本没有可写入的原 response。要求把完整事件流交付给同一 response 时，caller 必须在自己结束前 `join()` 对应 Run。

## 9. 取消与传播

`cancel()` 主动取消指定的直接调用 Run，并等待公共 Run API 返回终态。官方取消终态是 `interrupted`。

每个 Workflow 的 `cancel_on_caller_termination` 默认是 `true`：

- caller Run 失败或取消时，仍 active 的直接调用 Run 会被取消；
- 被取消 Run 再按它直接调用目标的配置继续逐层传播；
- caller 正常到达 End 不触发传播；
- 目标 Workflow 将该字段设为 `false` 时，该 Run 独立继续。

传播只使用已经保存的直接 caller→spawned relation，不按时间、event namespace、Graph Edge 或 Workflow name 猜测关系。官方已终态的 Run 不重复发送 cancel。

## 10. 观测与交付检查

运行监控的 Lifecycle scope 显示请求入口 Run 与全部被调用 Run；Workflow scope 显示匹配 Workflow 的 Run 及其后代；Run scope 只显示 exact Run。层级只来自 Registry 的 `caller_run_id -> spawned_run_id` 事实。

交付前确认：

- 目标是本次冻结配置中的 enabled Workflow UUID；
- operation ID 在 caller Run 内稳定且表达业务调用；
- 需要后续控制的 `run_id` 已保存，官方状态没有复制为第二套 State；
- `join()`、`check()` 或 fire-and-forget 符合预期结果交付方式；
- 大型结果通过 Store/Filesystem reference 交付；
- `cancel_on_caller_termination` 符合 caller 失败或取消后的预期；
- 循环有业务退出条件；
- 要进入同一公开 response 的输出在请求入口 Run 结束前完成收集。
