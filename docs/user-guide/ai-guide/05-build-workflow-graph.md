# 构建 Workflow Graph

本章把已经完成的 design record 转换为 Workflow metadata 和 `WorkflowGraphDocumentV1`。

完成结果是一份已经保存为 draft 的完整 Graph document。validation 和 publish 在[验证、运行与交付](08-validate-run-deliver.md)中完成。

## 1. 准备引用

开始前确认：

- active Configuration Repository 没有变化；
- 已读取当前 `/agent-shell/api/workflow-node-catalog`；
- design record 已明确 topology、State owner 和结束条件；
- Graph 使用的 Main Agent、Command 和 Workflow Event Output UUID 已记录；
- 缺少 Python-backed Component 时，先按[编写 Python extension](06-python-extensions.md)创建，再返回本章。

从已有 Graph 或示例复制 Node type、version、handle 或 Component UUID 前，先通过当前 Catalog 和当前 Repository 确认这些值仍然有效。

## 2. 创建 Workflow metadata

创建 Workflow 的 payload 示例：

```http
POST /agent-shell/api/workflows
```

```json
{
  "name": "ai-workflow",
  "description": "Runs the configured workflow nodes.",
  "is_model_entry": true
}
```

新 Workflow 固定从 `enabled=false` 开始。创建 payload 不能直接启用 Workflow；只有完整 Graph publish 成功后才会设置 `enabled=true`。

保存 response 中的 Workflow UUID 和精确 name。`enabled=true` 且 `is_model_entry=true` 的 Workflow name 是 `/compat/openai/v1/chat/completions` 可用的 `model` 值；全部 enabled Workflow 都可以作为跨 Workflow 调用目标。Main Agent name 和 UUID 不直接出现在 `/compat/openai/v1/models`。

## 3. Runtime metadata

Workflow metadata 还可以保存：

- `is_model_entry`：是否映射为 OpenAI-compatible model 入口，默认 `false`；只有与 `enabled=true` 同时满足时才可从公开入口启动；
- `workflow_event_output_id`：可空 Workflow Event Output reference；
- `response_stream_scheduling_id`：可空 Response Stream Scheduling Component reference；当前 Workflow 作为请求入口时选择本次 response 调度策略；
- `durability`：`sync|async|exit`，默认 `async`，原样传给官方 Run；
- `on_disconnect`：`cancel|continue`，默认 `cancel`；当前 Workflow 作为客户端请求入口时决定断开后的 Lifecycle 行为。

创建时省略这些字段会使用当前 backend default。显式提交的字段表示用户为该 Workflow 选择的 runtime value。

如果用户需要调整 Graph 运行限制，使用【系统 / 系统配置 / 限制策略】：

- `recursion_limit` 默认 `100000`，限制 Graph 执行步数，正常循环仍需业务退出条件；
- `max_concurrency` 默认 `20`，控制 Graph 内并发；留空时使用官方默认行为；
- `n_jobs_per_worker` 默认 `20`，控制单 worker 并行 Run 槽位；
- 三个字段只要求正整数，没有额外产品最大值，真实资源代价取决于 Workflow、Provider、Tool、进程和宿主机。

修改现有 Workflow 时先 GET，保留未修改的 metadata。metadata PUT 不改变当前 `enabled`。

Server-managed Workflow Run 的 Thread、checkpoint、State 与 history 由 LangGraph Dev runtime 统一拥有。项目不创建应用级 Checkpointer 组件；持久化写入时机由 Workflow 的官方 `durability` 配置决定。

需要调整公开响应的排队和排水时，先创建 Response Stream Scheduling Component：

```http
POST /agent-shell/api/blocks/response-stream-scheduling
```

```json
{
  "name": "Fair response stream",
  "queue": {
    "strategy": "request",
    "idle_timeout_seconds": 2,
    "max_batch_kb": 64,
    "send_interval_seconds": 0.05
  }
}
```

把 response UUID 写入可能作为请求入口的 Workflow metadata 的 `response_stream_scheduling_id`。省略或提交 `null` 时使用内置默认。该组件只排序和节流 Event Output 已批准的文本，不决定事件可见性或文本修饰。

需要公开 Command 或其他 Workflow-owned event 时，创建 Workflow Event Output，并把 UUID 写入 `workflow_event_output_id`。创建和编辑 package 的流程见[编写 Python extension](06-python-extensions.md)。

每个 Workflow 独立设置 `on_disconnect`。只有当前 Workflow 作为某次客户端请求入口时才读取该值：`cancel` 取消同一 Lifecycle 的全部 active Run，`continue` 让全部 Run 后台继续。被调用 Workflow 的该字段不参与当前请求的判断；Run 终态也不会触发隐式取消传播。

## 4. Graph document

Graph document 只包含 executable definition 和 layout：

```json
{
  "definition": {
    "schema_version": 1,
    "state_contract": "agent-shell.workflow.agent-invocations.v1",
    "nodes": [],
    "edges": []
  },
  "layout": {
    "nodes": {},
    "viewport": {
      "x": 0,
      "y": 0,
      "zoom": 1
    }
  }
}
```

`definition` 决定运行语义。`layout` 只保存 Node position 和 viewport。selection、color、CSS class、Vue Flow renderer 和临时 connection field 不进入 Graph document。

同一个 Workflow 只保存一份 current Graph document。draft 和 enabled 由同一 Workflow 的 `enabled=false` 或 `enabled=true` 表示，不存在第二份 Graph revision。

## 5. Publishable topology

publishable Graph 必须：

- 恰有一个 Start；
- 恰有一个 End；
- Start 至少有一条合法 outgoing Edge；
- 除 End 外的 executable Node 都从 Start 可达；
- Node、Edge、handle、role 和 Component reference 通过当前 Catalog 与 static validation。

以下 topology 都合法：

```text
Start -> End

Start -> Work Node
End 作为同一 Graph 中没有 incoming Edge 的 system Node

Start -> Work Node -> End
```

reachable executable Node 可以没有 outgoing Edge。该 path 会自然结束。End 可以没有 incoming Edge。

## 6. 单 Agent Graph 示例

下面示例要求 reference ledger 中已经存在 Main Agent UUID：

```json
{
  "definition": {
    "schema_version": 1,
    "state_contract": "agent-shell.workflow.agent-invocations.v1",
    "nodes": [
      {
        "id": "start",
        "type": "start",
        "type_version": 1,
        "config": {}
      },
      {
        "id": "worker",
        "type": "agent",
        "type_version": 1,
        "config": {
          "main_agent_id": "<main agent UUID>",
          "defer": false
        }
      },
      {
        "id": "end",
        "type": "end",
        "type_version": 1,
        "config": {}
      }
    ],
    "edges": [
      {
        "id": "start-worker",
        "source": "start",
        "source_handle": "next",
        "target": "worker",
        "target_handle": "in"
      },
      {
        "id": "worker-end",
        "source": "worker",
        "source_handle": "next",
        "target": "end",
        "target_handle": "in"
      }
    ]
  },
  "layout": {
    "nodes": {
      "start": {
        "x": 80,
        "y": 160
      },
      "worker": {
        "x": 360,
        "y": 160
      },
      "end": {
        "x": 640,
        "y": 160
      }
    },
    "viewport": {
      "x": 0,
      "y": 0,
      "zoom": 1
    }
  }
}
```

## 7. Node 规则

当前 Node type 为 Start、Agent、Command 和 End。以当前 Node Catalog 为准。

Start：

- config 是空对象；
- 直接映射 LangGraph `START`；
- output handle 是 `next`；
- 不读取或注入 client messages。

Agent：

- config 引用 `main_agent_id`，并保存 `defer`；
- input handle 是 `in`；
- normal output handle 是 `next`；
- 一次 Node execution 表示一次完整 Main Agent invocation。

Command：

- config 引用 `command_id`；
- input handle 是 `in`；
- dynamic output handle 是 `branch` 和 `dispatch`；
- Python callable 返回 Branch `activate` key、Agent `dispatch` task 和 Workflow State `update`；
- Branch 与 Dispatch 可以由同一次 invocation 同时产生；
- 每个非空 `activate` key 必须对应同源 Branch Edge 的 `branch_key`；
- 每个 dispatch item 的 `dispatch_key` 必须对应同源 Dispatch Edge。

End：

- config 是空对象；
- 直接映射 LangGraph `END`；
- input handle 是 `in`；
- 不执行 cleanup、output projection 或 background cancellation。

## 8. Node 和 Edge identity

Node ID 和 Edge ID：

- 在当前 Graph 内唯一；
- 以字母开头；
- 只使用字母、数字、`_` 和 `-`；
- 最长 64 字符。

同一个有向 `(source Node ID, target Node ID)` pair 只允许一条 Edge，Edge type、handle 或 routing key 不产生第二条连接身份。反向 `(target, source)` 是另一个有向 pair。需要把相同 Main Agent configuration 作为两个独立 target 时，创建两个不同 Agent Node ID。

handle ID：

- 来自当前 Catalog；
- 以小写字母开头；
- 只使用小写字母、数字和 `-`；
- 最长 64 字符。

每条 Edge 保存：

```text
id
source
source_handle
target
target_handle
optional branch_key
optional dispatch_key
```

Edge 必须从 source output handle 连接到 target 接受该 Edge type 的 input handle。

## 9. Normal、Branch 和 Dispatch Edge

Normal Edge 不保存 `branch_key` 或 `dispatch_key`。它由两端 Catalog endpoint 推导，并映射为 static activation。

Branch Edge 从 Command 的 `branch` handle 发出，并保存唯一 `branch_key`：

```json
{
  "id": "decision-review",
  "source": "decision",
  "source_handle": "branch",
  "target": "reviewer",
  "target_handle": "in",
  "branch_key": "review"
}
```

Command `activate` 可以返回零个、一个或多个不同 key。空集合表示不激活 successor，State update 仍提交，当前 path 自然结束。返回未知 key 会让 Run 受控失败。

Dispatch Edge 从 Command 的 `dispatch` handle 发出，并保存唯一 `dispatch_key`：

```json
{
  "id": "dispatch-item",
  "source": "planner",
  "source_handle": "dispatch",
  "target": "item-worker",
  "target_handle": "in",
  "dispatch_key": "item"
}
```

Dispatch target 必须是 Agent 的 task-aware input。同一个 Agent 不能同时使用 Dispatch Edge 和 Normal 或 Branch input。

同一 Dispatch Edge 可以被一个 Command invocation 中的多个 dispatch item 重复选择。compiler 为每一项创建一个 LangGraph `Send`，因此目标 Agent Node 会获得多次独立 invocation，并分别收到自己的 private `workflow_task`。两个不同 Agent Node ID 即使引用同一个 Main Agent UUID，也仍是两个不同 Graph target。

Command 的完整 Python contract 见[编写 Python extension](06-python-extensions.md)。

## 10. Fan-out、fan-in、leaf 和 loop

一个 source 的多条 Normal Edge 形成 fan-out，所有 target 在下一 Super-step 激活。

一个 executable target 的多个非 Start Normal source 形成 all-of fan-in。所有 source 必须在同一次运行中实际到达。

不要用以下结构表达互斥分支后的 join：

```text
Command -> branch A -> J
        -> branch B -> J
```

一次运行只选择 A 或 B 时，J 不会执行。

不要用多条进入 End 的 Edge表达“等待全部完成”。End 不执行 join 或 finalization。先让所有 source 进入 executable finalizer，再从 finalizer 进入 End。

loop 必须通过 Command 或其他业务逻辑提供可达 exit path。只有 static Normal Edge 的环没有受控出口，会一直运行到失败边界。

Command 的动态 pending worker 需要 downstream aggregation 时，可以在下游 aggregation Agent Node 使用 `defer=true`。该设置让 Agent Node 等待当前 Graph 中其他 pending task 完成后再执行。

## 11. 保存 draft

把完整 Graph document 保存为 draft：

```http
PUT /agent-shell/api/workflows/<workflow UUID>/draft
Content-Type: application/json

<complete WorkflowGraphDocumentV1>
```

`PUT /draft` 执行基础 wire parsing。成功时保存 document，并原子设置 `enabled=false`。

draft save 不执行完整 Node Catalog、topology、reference、Python package 或 Agent assembly validation。基础字段类型、ID、extra field 和 layout 数值不合法时仍返回 422。

保存已 enabled Workflow 的 draft 会立即将它设为 disabled，并从 `/compat/openai/v1/models` 和跨 Workflow 调用的 enabled target 集合移除。`is_model_entry` 保留用户选择，但 disabled Workflow 不发布为 model。

保存后 GET 回读：

```text
GET /agent-shell/api/workflows/<workflow UUID>
GET /agent-shell/api/workflows/<workflow UUID>/graph
```

核对 Workflow UUID、name、`enabled=false`、Node、Edge 和 layout。

## 12. 本章完成结果

进入 validation 前确认：

- Workflow metadata 已保存并回读；
- runtime setting 使用默认值或用户明确选择的值；
- Graph 恰有一个 Start 和一个 End；
- Start 至少有一条合法 outgoing Edge；
- 除 End 外的 Node 都从 Start 可达；
- Node type、version、config 和 handle 来自当前 Catalog；
- Component reference 使用 API 返回的 UUID；
- Command 的 outgoing Edge 只使用 Branch 或 Dispatch handle；
- Dispatch Edge 的 target 是 Agent Node；
- 每个有向 source/target Node pair 只有一条 Edge；
- key 与 Python callable 的可能返回值一致；
- parallel State owner 和 all-of source 合法；
- loop 有业务可达 exit；
- layout 不承载运行语义；
- 完整 Graph document 已保存为 draft 并回读一致。

如果缺少或需要修改 Python-backed Component，阅读[编写 Python extension](06-python-extensions.md)并重新保存 draft。需要跨 Workflow Run 调用时阅读[跨 Workflow Run 调用](07-cross-workflow-runs.md)。随后阅读[验证、运行与交付](08-validate-run-deliver.md)。
