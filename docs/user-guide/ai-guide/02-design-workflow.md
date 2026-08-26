# 设计 Workflow

本章把用户需求转换为 topology、State ownership、Agent input 和结束条件。完成设计后再创建 Component、Agent 和 Workflow。

本章同时包含 Agent Shell 的运行约束和编排建议。标为“系统约束”的内容必须遵守；标为“建议”的内容可以根据业务调整。

## 1. 先选择最小结构

先判断是否需要 LLM。

不需要语言理解、模型推理或模型选择 Tool 时，使用 Command 或 Task Dispatcher 组成确定性 Workflow。不要为了“强行使用AI”而增加 Agent Node。

需要模型能力时，为对应步骤使用 Agent Node。一个 Agent Node 表示一次完整 Main Agent invocation，包含该 Agent 内部的全部 model-tool loop。

三个最小起点是：

```text
验证通路：
Start -> End

脚本：
Start -> Command -> End

AI Agent：
Start -> Agent -> End
```

## 2. 选择执行机制

使用 Normal Edge：

- 下一步在设计时已经确定；
- 一个 source 完成后需要固定激活一个或多个 target；
- 设计时已知多个 Agent，可以直接串行或 fan-out。

使用 Command：

- 需要确定性 condition；
- 需要更新 Workflow State；
- 需要选择 Branch Edge；
- 需要表达 loop exit、轮询状态或 background controller；
- 需要确定性数据转换。

使用 Agent Node：

- 需要语言理解、非确定性推理或模型选择 Tool；
- 一次 Node invocation 应完成一个完整 Agent loop；
- Agent 的模型、Tool、Middleware 和 Subagent 由 Main Agent configuration 决定。

使用 Task Dispatcher：

- task 数量、payload 或 target 在运行时才知道；
- 每个 task 需要独立 Agent worker invocation；
- 这是 dynamic map，不是设计时已知的普通 fan-out。

使用 synchronous Subagent：

- Main Agent 需要由模型决定是否委派给 specialist；
- Main Agent 等待 Subagent 返回后继续同一个 Agent loop；
- 不需要独立 Workflow Run 或 State。

使用 background Run：

- child 必须拥有独立 `run_id` 和独立 Workflow State；
- launcher 需要在 child 仍运行时继续；
- parent 需要自行决定检查、等待、取消或忽略 child；
- task 需要由 enabled child Workflow 表达。

普通 parallel Node、异步 Python、synchronous Subagent 和 Task Dispatcher worker 都不需要 background Run。

## 3. LangGraph 执行约束

以下内容是系统约束。

### 3.1 Super-step

LangGraph 按 Super-step 执行 Graph：

1. 根据上一轮结果确定本轮 scheduled Node；
2. 执行本轮全部 Node，多个 Node 可以并行；
3. 使用各 State channel 的 reducer 合并 Node update；
4. 根据合并后的 State 生成下一 Super-step 的 task。

同一 Super-step 内的 parallel Node 读取同一个 boundary State snapshot。一个 Node 在本轮返回的 update，要到下一 Super-step 才对其他 Node 可见。

parallel Node 的开始时间、结束时间和 update 到达顺序不承载业务顺序。需要稳定顺序时，使用 Edge、稳定业务 identity、sequence field 或显式排序。

### 3.2 Normal Edge、fan-out 和 fan-in

Normal Edge 表示 source 完成后无条件激活固定 target。

一个 source 连接多个 Normal Edge 时，所有 target 在下一 Super-step 激活，形成 fan-out。

同一个 executable target 存在多个非 Start Normal source 时，Agent Shell 把它们编译为 all-of fan-in。所有 source 都实际完成后才激活 target。

```text
A -> B
A -> C

B -> J
C -> J
```

这里 B 和 C 并行。J 等待 B、C 都完成。

如果 B 和 C 来自 mutually exclusive branch，本次运行只会激活其中一个，J 将无法满足 all-of 条件。互斥分支不要直接汇聚到同一个 all-of target。

Start 使用入口激活语义，不参与 all-of fan-in：

```text
Start -> J
Start -> A -> J
```

这会让 J 在启动时执行一次，并在 A 完成后再次执行一次，不表示 Start 和 A 的汇聚等待。

End 是 termination sentinel，不是 executable join Node。多条进入 End 的 Edge 彼此独立。需要等待多个分支后执行收尾时，先汇聚到 executable finalizer Node，再连接 End。

### 3.3 Dynamic routing

一个 source 只使用一种 routing mechanism。

普通 Node 和 Agent Node 使用 static Normal Edge。Command 使用 Branch Edge。Task Dispatcher 使用 Dispatch Edge。

Command 和 Task Dispatcher 不再配置 static Normal output。否则 static route 和 dynamic route 可能同时执行；当前 Catalog 也不会为它们提供 normal output handle。

### 3.4 Graph 结束

下一 Super-step 没有 runnable task 时，Graph 完成。

reachable executable Node 可以没有 outgoing Edge。该 path 在 Node 完成后自然结束。

某条 path 到达 End 只结束该 path，不取消其他 active branch 或 independent background Run。

循环必须有业务可达的退出 path。`recursion_limit` 和 `execution_timeout_seconds` 是失败边界，不是正常业务完成条件。

## 4. Workflow State 和运行数据

Workflow root State 声明四个 channel：

- `shared_vars` 保存当前 Run 的轻量控制状态；
- `agent_invocations` 保存 Agent invocation identity 和 `result_ref`；
- `background_tasks` 保存 background task handle 或最近一次 snapshot；
- `files` 保存当前 Run 的 Deep Agents StateBackend 文件状态。

Task Dispatcher 通过 `Send` 为单个 worker 注入私有 `workflow_task`。它不是 Workflow root State channel。

`runtime.context` 保存 lifecycle、run、可空 checkpoint thread、Node、Agent 和 background command 等当前 invocation identity 和服务入口。

`runtime.store` 保存 Lifecycle input、完整 Agent invocation artifact、background task record 和其他通过 reference 读取的结构化数据。

### 4.1 `shared_vars`

`shared_vars` 的值必须是 JSON-compatible data。它的 reducer 对 top-level key 执行 shallow merge。

下面的 update 会替换整个 `controller` value：

```json
{
  "shared_vars": {
    "controller": {
      "phase": "poll",
      "status": "running"
    }
  }
}
```

建议一个 logical owner 管理一个 top-level key：

```json
{
  "shared_vars": {
    "controller": {},
    "research_a": {},
    "research_b": {},
    "finalization": {}
  }
}
```

不要让 parallel Node 同时重写同一个 top-level value。让各 branch 写入独立 key，再由 downstream aggregation Node 生成统一结果。

`shared_vars` 适合 phase、status、cursor、计数器、ID、布尔条件、短小 JSON 和 artifact reference。大型正文、数据集或二进制数据不要直接放入控制 State。

### 4.2 `agent_invocations`

`agent_invocations` 由 Agent wrapper 写入。每条记录保存 invocation、Workflow、Node、Agent identity、时间和 `result_ref`。

完整 Agent messages 保存在 Lifecycle Store。downstream Agent 可以由 AAP 选择因果可见的 invocation record，再按 `result_ref` 加载 artifact。

不要根据 mapping 插入顺序、Agent 开始时间或结束时间推导并行业务顺序。

### 4.3 `background_tasks`

调用 `start_workflow()`、`check()` 或 `cancel()` 后，可以把 handle 或 snapshot 的 `model_dump(mode="json")` 结果写入 `background_tasks`。

业务 phase、winner、pending ID 和聚合进度放入 `shared_vars`。background task 的运行事实放入 `background_tasks`。

### 4.4 `workflow_task`

Task Dispatcher 为每个 Agent worker 注入：

```json
{
  "dispatcher_node_id": "dispatcher",
  "dispatcher_invocation_id": "<invocation UUID>",
  "task_id": "item:42",
  "dispatch_key": "item",
  "payload": {
    "item_id": "42"
  }
}
```

payload 只携带当前 worker 真正需要的 JSON data。大型材料先保存到 Store 或 Filesystem，再传递 reference。

### 4.5 Filesystem 和 Store

`files` 适合 current Run 的 Agent 工作文件。独立 background Run 不自动复制或 merge parent 的 `files` channel。

大型正文、数据集和跨 Run artifact 使用 mapped Filesystem 或明确的 Store namespace，并在 State 或 task payload 中保存稳定 reference。

Node local variable 只存在于当前 invocation。需要影响下一 Super-step 的数据必须返回 State update，或者写入 Store 或 Filesystem。

## 5. Agent 初始材料

Workflow root State 不包含 `messages`。Start Node 不注入客户端消息。Agent Node 默认以私有空 `messages` 调用 Main Agent graph。

如果 Agent 需要使用当前 request、Dispatcher task、Workflow State snapshot、上游 invocation 或文件，为该 Agent 配置 AAP 或其他具有明确输入 contract 的 Middleware。

System Prompt 保存每次 invocation 都适用的稳定角色和规则。AAP 负责本次运行材料的选择、裁剪、role 编排和初始消息构造。

不同 Agent 可以使用不同 AAP，也可以不使用 AAP。不要把完整 request 自动复制给每个 Agent。

## 6. 常用 topology

### 6.1 固定顺序

```text
Start -> Fetch -> Analyze -> Write -> End
```

每个 Node 完成一个明确步骤。下一步固定时使用 Normal Edge。

### 6.2 固定并行

```text
             -> Agent A ->
Start -> Fan               Join -> End
             -> Agent B ->
```

设计时已知 Agent A 和 Agent B 时，直接使用 Normal Edge fan-out。为两个 branch 分配不同 State owner。Join 的所有 source 必须在同一次运行中实际到达。

### 6.3 条件和循环

```text
Poll Command
  -> pending -> Delay Command -> Poll Command
  -> ready   -> Process -> End
  -> failed  -> Failure -> End
```

一次 Poll invocation 建议只查询一次外部状态，更新精简 observation，再选择一个 successor。

`next_poll_at` 只是业务数据，不会自动创建 timer 或 wakeup。当前没有通用 delay command；在 async Node callable 中使用 `await asyncio.sleep(...)` 会占用当前 Node invocation 时间，并受 Workflow execution timeout 约束。

### 6.4 动态 Agent map

```text
Task Dispatcher
  -> worker(item-1)
  -> worker(item-2)
  -> worker(item-N)
```

只有运行时才知道 task 集合时使用 Task Dispatcher。每个 task 使用稳定 `task_id`、明确 `dispatch_key` 和精简 payload。

### 6.5 Independent child Run

```text
Start child
  -> persist handle
  -> check
  -> business decision
  -> optional cancel or finalize
  -> End
```

只有 child 需要独立 Run 和 State 时使用 background Run。具体 command、cancellation 和 result handoff 见[使用 background Run](06-background-runs.md)。

## 7. 输出 design record

创建配置前写出：

```text
observable result: <用户将看到或取得什么>
workflow role: parent | child
topology: Start -> ... -> End
agent nodes: <Main Agent role，或 none>
deterministic nodes: <Command / Task Dispatcher role，或 none>
state owners: <top-level key -> logical owner>
agent input: <System Prompt / AAP source / workflow_task / result_ref>
large artifacts: <Store namespace 或 virtual Filesystem path>
success condition: <业务条件>
failure condition: <业务条件>
loop exit: <业务可达 path，或 no loop>
background policy: <none | wait | poll | fire-and-forget | cancel redundant child>
```

## 8. 本章完成结果

进入配置阶段前确认：

- 已选择最少的 Node 和 execution mechanism；
- 已区分固定 fan-out、dynamic map、Subagent 和 background Run；
- 每个 `shared_vars` top-level key 有明确 owner；
- parallel branch 不会覆盖同一个 top-level value；
- 大型 artifact 使用 reference；
- 每个 Agent 的初始材料来源明确；
- loop 和 background controller 有业务退出条件；
- all-of fan-in 的所有 source 都会实际到达；
- 已形成 design record。

Graph 包含 Agent Node 时，下一步阅读[配置 Agent](03-configure-agent.md)。没有 Agent Node 时，直接阅读[构建 Workflow Graph](04-build-workflow-graph.md)。
