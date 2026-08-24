# Workflow 编排总则

Workflow Graph 可以表达串行、并行、循环、动态派发、Agent 协作和 background Run。Topology 由业务决定。本章先说明 Agent Shell 的运行事实，再给出可按场景采用的数据与编排建议。

阅读本章时按以下标签理解约束强度：

- **运行事实**：由 Agent Shell 和 LangGraph 当前实现决定；
- **建议**：用于提高可读性、稳定性和可维护性，可以根据业务调整。

## 1. 运行事实

### 1.1 Super-step

LangGraph 按 Bulk Synchronous Parallel 模型执行 Graph。每个 Super-step 依次完成：

1. 根据上一轮结果确定本轮 scheduled Node；
2. 执行本轮全部 Node，多个 Node 可以并行；
3. 等待本轮全部 Node 完成，或在未处理异常时使 current Run 失败；
4. 使用各 State channel 的 reducer 合并 Node update；
5. 根据合并后的 State 生成下一 Super-step 的任务。

同一 Super-step 内的 parallel Node 读取同一个 boundary State snapshot。本轮某个 Node 写入的 update，要到下一 Super-step 才对其他 Node 可见。

parallel Node 的开始时间、结束时间和 update 到达顺序不承载业务顺序。需要稳定顺序时，使用 Edge、stable business identity、sequence field 或显式排序。

### 1.2 Agent Node

Agent Node 在 parent Workflow Graph 中表示一次完整的 Main Agent subgraph invocation。一次 invocation 包含 Agent 内部全部 model-tool loop。parent Graph 在 Agent invocation 返回后，才调度该 Agent Node 的 successor。

同一 parent Graph Super-step 中的其他 parallel Node 可以同时运行；parent Graph 会等待本轮全部 scheduled Node 完成。

### 1.3 Normal Edge、fan-out 和 fan-in

Normal Edge 表示 source Node 完成后，无条件激活固定 target。

一个 source 连接多个 Normal Edge 时形成 fan-out，downstream Node 会在下一 Super-step 被同时激活。

同一个普通 executable Node 存在多个非 Start Normal 入边时，Agent Shell 将这些来源编译为 `all-of fan-in barrier`。全部来源都实际完成后，target 才会被激活。

Start Node 使用入口激活语义，不参与 `all-of fan-in barrier`：

```text
Start -> J
A -> J
```

这组连接会分别激活 J，不表达 Start 和 A 的汇聚等待。

End Node 是 termination sentinel，不是 executable join Node。多条进入 End 的 Edge 彼此独立。需要等待多个分支全部完成时，可以先汇聚到一个 executable Node，再从该 Node 进入 End。

如果 `all-of fan-in barrier` 的 source Node 属于 mutually exclusive branch，本次运行中没有被激活的 source Node 不会到达，aggregation Node 也不会执行。

### 1.4 State update

Node 返回 State partial update，每个 State channel 按自己的 reducer 合并 update。current Workflow State 的正式 channel 包括：

- `shared_vars`；
- `agent_invocations`；
- `background_tasks`；
- `files`。

Command Node 和 Task Dispatcher 的 update 只能使用这些已声明 channel。State value 需要满足对应 channel 的当前 schema。

### 1.5 Graph 结束

下一 Super-step 没有 runnable task 时，Graph 完成。

可达 Node 可以没有 outgoing Edge，这条 path 会自然结束。某条 path 到达 End，只结束该 path；其他 parallel branch 和 background Run 可以继续运行。

`recursion_limit` 和 `execution_timeout_seconds` 是 Run 的失败边界。循环的正常完成条件由业务状态和退出 path 表达。

## 2. 数据放置建议

建议先区分 control state、working data、artifact 和 runtime identity。清晰的数据归属能让 Workflow 接近一段可维护的程序。

| 数据类型 | 建议位置 | 适合保存 |
| --- | --- | --- |
| current Run 的轻量业务状态 | `shared_vars` | phase、status、cursor、计数器、ID、布尔条件、短小 JSON、artifact reference |
| Agent 完成记录 | `agent_invocations` | Shell 生成的 Agent identity 和 `result_ref` |
| background task 状态 | `background_tasks` | task handle、最近一次 `check()` 得到的 snapshot |
| Agent 工作文件 | `files` | current Run 内由 Deep Agents Filesystem 使用的文件 |
| 动态 worker 输入 | `workflow_task` | Task Dispatcher 为单个 worker 注入的 task identity 和 payload |
| Agent 初始提示词 | Agent private `messages` | 由可选的 AAP Middleware 在 Agent invocation 开始前构造 |
| 当前运行身份和服务入口 | `runtime.context` | lifecycle/run、可空 checkpoint thread、node/agent identity、background commands |
| Lifecycle 公共事实和 invocation artifact | `runtime.store` | request snapshot、完整 Agent messages、结构化 artifact、reference target |
| 大型正文或二进制 artifact | mapped Filesystem 或业务拥有的 Store namespace | 报告、数据集、长文本、图片、跨 Run 文件 |

### 2.1 `shared_vars`

`shared_vars` 适合作为 Workflow 的 short-term memory，值必须是 JSON-compatible data。它的 reducer 对 top-level key 执行 shallow merge：

```python
{
    **current_shared_vars,
    **shared_vars_update,
}
```

下面的 update 会替换整个 `controller` value：

```python
{
    "shared_vars": {
        "controller": {
            "phase": "poll",
            "status": "running",
        }
    }
}
```

建议一个 logical owner 管理一个 top-level key：

```json
{
  "controller": {},
  "order_polling": {},
  "research_queue": {},
  "finalization": {}
}
```

parallel branch 可以分别使用独立 key：

```json
{
  "branch_a": {"status": "done"},
  "branch_b": {"status": "running"}
}
```

多个 parallel Node 同时重写同一个 top-level key 时，业务结果容易依赖 reducer update 顺序。需要共同修改同一对象时，可以让各 branch 写入独立 slot，再由 downstream aggregation Node 生成新对象。

### 2.2 `agent_invocations`

`agent_invocations` 由 Agent wrapper 写入，建议作为 Shell-owned channel 读取。它保存轻量 reference：

```json
{
  "<invocation-id>": {
    "invocation_id": "...",
    "workflow_id": "...",
    "workflow_node_id": "...",
    "agent_id": "...",
    "invoked_at": 0,
    "result_ref": "..."
  }
}
```

完整 Agent messages 保存在 Lifecycle Store。downstream Agent 可以通过 AAP 选择因果可见的 invocation record，再按 `result_ref` 加载 artifact。State 中保留 reference，可以减少 checkpoint 体积，也能避免在多个 Node 之间反复复制长消息。

### 2.3 `background_tasks`

`background_tasks` 适合保存已经启动或检查过的 background task snapshot：

```json
{
  "task-uuid": {
    "task_id": "task-uuid",
    "status": "running"
  }
}
```

调用 `start_agent()`、`start_workflow()`、`check()` 或 `cancel()` 后，先对 handle/snapshot 调用 `model_dump(mode="json")`，再写入 State。

业务上的 winner、待检查 task ID 和聚合进度可以放在 `shared_vars`；background task 的运行事实放在 `background_tasks`。

### 2.4 `workflow_task`

`workflow_task` 是 Task Dispatcher 通过 `Send` 注入 worker 的私有输入：

```json
{
  "dispatcher_node_id": "dispatcher",
  "dispatcher_invocation_id": "...",
  "task_id": "item:42",
  "dispatch_key": "item",
  "payload": {"item_id": "42"}
}
```

它适合表达“这一次 Agent invocation 需要处理什么”。AAP 可以将 payload 编排进该 worker 的私有 `messages`。

Task Dispatcher payload 建议只携带当前 worker 真正需要的任务数据。大型材料可以保存到 Filesystem 或 Store，并在 payload 中传递 reference。

### 2.5 `files` 与 mapped Filesystem

`files` 是 Agent Filesystem 使用的 State channel，适合 current Run 的工作文件。频繁变化的大型数据会增加 State；Workflow 启用 Checkpointer 时也会增加 checkpoint 成本。大型正文、数据集和跨 Run artifact 可以写入 mapped Filesystem，并在 `shared_vars`、`workflow_task` 或 Store record 中保存路径和 identity：

```json
{
  "report": {
    "path": "/reports/order-42.md",
    "media_type": "text/markdown"
  }
}
```

路径使用 current Agent 可见的虚拟 Filesystem path。

### 2.6 `runtime.store`

Store 适合保存需要通过 reference 读取的完整结构化数据。业务代码使用 Store 时，建议使用业务拥有的独立 namespace 和稳定 key。平台拥有的 Lifecycle input、invocation artifact 和 background task namespace 由 Shell 管理。

### 2.7 Node local variable

Node 函数中的普通 Python local variable 只在 current invocation 中存在：

```python
async def command(state, runtime):
    observation = await query_status()
```

需要影响下一 Super-step 的数据，应返回到 State、写入 Store，或者保存到 Filesystem。

Node 可能因 retry 或运行恢复而重新执行。调用外部 API、创建资源或启动 background Run 时，可以使用稳定 operation identity，使重复执行保持幂等。

## 3. 模拟单线程程序的推荐结构

很多 Workflow 可以视为一个带 program counter 的单线程状态机。这类 Graph 通常每轮只激活一个业务 Node。Node 读取当前 machine state，完成一次状态转换，写回新状态，再选择一个 successor。

### 3.1 最小状态机寄存器

适合单个对象的查询、等待和处理：

```json
{
  "shared_vars": {
    "controller": {
      "pc": "poll",
      "status": "running",
      "subject": {"type": "order", "id": "order-42"},
      "iteration": 0,
      "next_poll_at": null,
      "last_observation": null,
      "result_ref": null,
      "error": null
    }
  }
}
```

字段建议：

- `pc`：下一段逻辑或当前 logical location；
- `status`：`running`、`waiting`、`succeeded`、`failed` 等业务状态；
- `subject`：当前处理对象的稳定 identity；
- `iteration`：已经完成的观察次数，用于 Debug；
- `next_poll_at`：下一次建议检查时间；
- `last_observation`：最近一次外部状态的精简快照；
- `result_ref`：完整结果的 Store key 或 Filesystem path；
- `error`：业务可处理的错误摘要。

`iteration` 用于记录事实，不需要作为隐藏的终止上限。是否继续由业务条件决定。

`next_poll_at` 是业务数据，不会自动创建 timer、delay 或 wakeup。轮询 Node 需要读取该值，并用 Graph control flow 和 async wait 表达实际等待。

### 3.2 Program counter + memory

适合步骤较多、控制流仍保持单线程的 Workflow：

```json
{
  "shared_vars": {
    "program": {
      "pc": "fetch",
      "status": "running"
    },
    "memory": {
      "request_id": "req-42",
      "source_ref": "/inputs/req-42.json",
      "normalized_ref": null,
      "decision": null,
      "output_ref": null
    }
  }
}
```

Graph 可以将 `pc` 映射为不同 Branch Edge：

```text
fetch -> normalize -> decide -> write -> End
                       |
                       +-> wait -> decide
```

`program` 保存控制位置，`memory` 保存业务寄存器。较大的中间结果通过 reference 连接。这种结构方便 AI 判断当前步骤、已有数据、下一步和完成条件。

### 3.3 小型工作队列

适合在一个逻辑线程中依次处理多个 item：

```json
{
  "shared_vars": {
    "queue": {
      "pending": ["item-2", "item-3"],
      "current": "item-1",
      "completed": {
        "item-0": {"result_ref": "/results/item-0.json"}
      },
      "failed": {}
    }
  }
}
```

每轮完成一次 transition：

```text
处理 current
  -> 写入 completed 或 failed
  -> 从 pending 选择下一个 current
  -> pending 为空时结束
```

队列较小时可以直接保存在 `shared_vars`。队列和结果集较大时，可以将完整集合放入 Store 或 Filesystem，State 只保留 source reference、cursor、current identity 和 remaining count。

### 3.4 小型 entity table

适合少量对象具有各自状态，调度仍由一个 controller 决定：

```json
{
  "shared_vars": {
    "scheduler": {
      "ready": ["job-2"],
      "waiting": ["job-1"],
      "current": "job-2"
    },
    "jobs": {
      "job-1": {
        "status": "waiting",
        "next_poll_at": "2026-08-24T12:00:00Z",
        "result_ref": null
      },
      "job-2": {
        "status": "ready",
        "next_poll_at": null,
        "result_ref": null
      }
    }
  }
}
```

`scheduler` 选择下一个 job，`jobs` 保存每个 entity 的 compact state。如果多个 parallel Node 会修改不同 job，可以按 owner 拆分 top-level key，或者由单一 aggregation Node 更新整个 `jobs` table。

### 3.5 Background Run controller

适合 parent Workflow 启动 child Run 后轮询状态：

```json
{
  "shared_vars": {
    "background_controller": {
      "phase": "poll",
      "task_ids": ["task-a", "task-b"],
      "pending_ids": ["task-a", "task-b"],
      "winner_task_id": null,
      "result_ref": null
    }
  },
  "background_tasks": {
    "task-a": {"task_id": "task-a", "status": "running"},
    "task-b": {"task_id": "task-b", "status": "pending"}
  }
}
```

建议的职责分配：

- `shared_vars.background_controller` 保存业务决策；
- `background_tasks` 保存最近取得的 task snapshot；
- child 完整输出保存在 child Run 自己的 Store/Filesystem；
- parent 保存后续需要读取的 reference。

如果业务希望 parent 结束前取消冗余 child Run，可以增加 finalizer Node：

```text
poll
  +-- still_running -> delay -> poll
  +-- succeeded     -> finalize -> End
  +-- failed        -> finalize -> End
```

finalizer 可以只处理 current Workflow 启动并记录的 task ID。

## 4. 轮询循环建议

轮询循环可以让一次 Super-step 完成一次逻辑观察：

```text
Poll Command
  +-- pending  -> Poll Command
  +-- ready    -> Process Node
  +-- failed   -> Failure Node
  +-- complete -> End
```

一次轮询建议完成以下动作：

1. 从 `shared_vars` 读取 controller；
2. 查询一次外部状态；
3. 将精简 observation 写回 controller；
4. 计算下一状态；
5. 激活零个或一个 successor。

这种设计接近单线程程序中的一次 loop iteration；Workflow 启用 Checkpointer 时，checkpoint 也能对应清晰的状态转换。

轮询频率可以根据外部服务 SLA、完成延迟，以及启用 Checkpointer 时的 checkpoint 成本配置。异步 Python 中使用：

```python
await asyncio.sleep(poll_interval_seconds)
```

等待发生在 current Node invocation 内，会延长该 Node 和当前 Super-step。轮询仍受 Workflow 的 `execution_timeout_seconds` 约束。

较长的外部任务也可以使用 background Run。parent 通过稳定 `operation_id` 启动任务，在后续 Super-step 中调用 `check()`，再根据 snapshot 路由。

## 5. Node 与控制流选择建议

### 5.1 固定 topology

Node 数量和连接关系在设计时已知时，可以直接使用 Normal Edge、Branch Edge 和 Agent Node。已知数量的多个 Agent 可以通过 fan-out 并行激活。

Task Dispatcher 主要用于运行时才确定 task 数量、payload 或 target 的 dynamic map 场景。

### 5.2 Command Node

Command Node 适合 condition、State transition、loop exit、successor selection、background Run control、外部状态轮询和确定性数据转换。

Command script 可以返回：

```python
{
    "activate": ["next-branch"],
    "update": {
        "shared_vars": {
            "controller": next_controller
        }
    }
}
```

`activate` 可以为空，也可以包含一个或多个 Branch Edge key。

### 5.3 Agent Node

Agent Node 适合需要语言理解、工具选择、非确定性推理或 Agent loop 的步骤。statically known Agent 可以由 Edge 直接激活。Agent 初始提示词需要动态材料时，建议使用 AAP Custom Middleware。

确定性状态转换可以放在 Command Node，让 Agent 专注于需要模型能力的工作。

### 5.4 Task Dispatcher

Task Dispatcher 适合运行时 dynamic map：

```text
Dispatcher
  -> worker(item-1)
  -> worker(item-2)
  -> worker(item-N)
```

每个 task 使用稳定 `task_id` 和精简 JSON payload。downstream aggregation Agent 可以设置 `defer=true`，等待 current Graph 中的 pending task 完成。

### 5.5 Background Run

background Run 适合 detached child execution。它拥有独立 `run_id` 和 State；background child Workflow 根据自己的 `checkpointer_id` 决定是否拥有 `checkpoint_thread_id` 和 checkpoint，background Agent 始终不装配 Checkpointer。

parent 和 child 通过明确的 handle、Store reference 或 mapped Filesystem artifact 交换信息。parent 是否等待、轮询、取消或忽略 child，由业务决定。

## 6. 并行数据建议

parallel branch 可以为每个 owner 使用独立 top-level key：

```json
{
  "shared_vars": {
    "research_a": {
      "status": "done",
      "result_ref": "/results/a.md"
    },
    "research_b": {
      "status": "running",
      "result_ref": null
    }
  }
}
```

aggregation Node 读取这些 slot，再生成统一结果：

```json
{
  "shared_vars": {
    "summary": {
      "status": "ready",
      "source_refs": [
        "/results/a.md",
        "/results/b.md"
      ]
    }
  }
}
```

parallel branch 产生的列表如果需要稳定顺序，可以同时保存 `sequence`、`task_id` 或其他 business key，并在汇总时显式排序。

## 7. AAP 建议

Agent Additional Prompt（AAP）是可选的 Custom Middleware template。需要为某个 Agent 动态生成初始提示词时，可以使用 AAP 从以下来源选择材料：

- Lifecycle request `messages[]`；
- 当前 `workflow_task`；
- `workflow_state_snapshot`；
- 前序 `agent_invocations` artifact；
- Runtime Store；
- Agent Filesystem。

不同 Agent 可以装配不同 AAP，也可以不装配 AAP。AAP 适合完成 current Agent 的材料选择、role 编排和初始 `messages` 构造。

## 8. 模型配置建议

AI 可以先描述 Model Requirement，例如：

- 支持 tool calling；
- 支持 structured output；
- 需要较大的 context window；
- 需要 multimodal input；
- 偏向速度、成本或推理能力。

用户负责创建 Model Connection，并在 Model Mapping 中将 Model Requirement 绑定到真实连接。

多个 Agent 的能力要求相同时，可以复用同一个 Model Requirement 和 Model Connection。只有角色确实需要不同模型能力时，再拆分多个要求。

## 9. 编排检查清单

保存 Workflow 前，建议检查：

- 每个 loop 是否存在业务可达的退出 path；
- `shared_vars` 的每个 top-level key 是否有清晰 owner；
- parallel branch 是否会同时覆盖同一个 top-level key；
- 大型正文是否已经改用 Store/Filesystem reference；
- `all-of fan-in barrier` 的全部来源是否会在同一次运行中到达；
- mutually exclusive branch 是否被汇聚到同一个 all-of target；
- Task Dispatcher payload 是否只包含 worker 需要的数据；
- background task 是否使用稳定 `operation_id`；
- parent 是否需要等待或取消 background child；
- Agent 是否需要 AAP 构造初始提示词；
- State 是否只保存下一步 routing 和恢复真正需要的数据；
- 正常完成条件是否由业务状态表达。

下一步：[Management API、对象关系与事实发现](01-api-and-discovery.md)。
