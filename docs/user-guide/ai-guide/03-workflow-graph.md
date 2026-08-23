# 创建 Workflow Graph

## 创建 parent Workflow

parent Workflow 创建后固定为 `enabled=false` 的 draft 状态；创建请求中的 `enabled` 会被忽略，只有 `PUT /api/workflows/{id}/graph` 能将它设为 `true`：

```http
POST /api/workflows

{
  "name": "ai-workflow",
  "workflow_role": "parent",
  "description": "Runs the configured workflow nodes.",
  "workflow_event_output_id": null,
  "recursion_limit": 1000000,
  "execution_timeout_seconds": 1200,
  "max_concurrency": 100
}
```

## 合法的最小 topology

正式 Graph 的固定 system Node 是唯一 Start 和唯一 End，不要求 Agent 或其他 Work Node。以下三种 topology 都合法：

```text
1. Start -> End

2. Start -> Work Node
   End 是同一 Graph 中没有 incoming Edge 的孤立 system Node

3. Start -> Work Node -> End
```

可达的普通 Work Node 没有 outgoing Edge 时，该 path 自然结束。一般 Workflow 仍建议包含完成业务所需的 Work Node，并让需要明确 exit condition 的 path 显式连接 End。condition、State update 和 successor selection 全部写在 Command Node 中，Graph 只声明 candidate Edge。

下面是包含 Agent Node 的第三种 topology 完整示例；正式 Graph 的最低结构要求见前两种 topology：

```json
{
  "definition": {
    "schema_version": 1,
    "state_contract": "agent-shell.workflow.agent-invocations.v1",
    "nodes": [
      {"id": "start", "type": "start", "type_version": 1, "config": {}},
      {
        "id": "worker",
        "type": "agent",
        "type_version": 1,
        "config": {"main_agent_id": "<main-agent UUID>", "defer": false}
      },
      {"id": "end", "type": "end", "type_version": 1, "config": {}}
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
      "start": {"x": 80, "y": 160},
      "worker": {"x": 360, "y": 160},
      "end": {"x": 640, "y": 160}
    },
    "viewport": {"x": 0, "y": 0, "zoom": 1}
  }
}
```

`source_handle` 和 `target_handle` 是 Edge wire 的组成部分；Vue Flow temporary field 不属于 Graph document。

同一个 Workflow 只保存这一份 Graph。draft 和 enabled Workflow 在同一个列表中，以 `enabled=false/true` 区分；没有 revision、第二份 Graph 或第二个 scheduler。

保存 API：

```text
PUT  /api/workflows/{id}/draft     保存当前 Graph document，并原子设置 enabled=false
POST /api/workflows/{id}/validate  只读返回当前 candidate Graph document 的完整 validation report
PUT  /api/workflows/{id}/graph     完整 validation 通过后原子写入 Graph document 和 enabled=true
GET  /api/workflows/{id}/graph     读取当前唯一 Graph document
```

【`PUT /draft`】不执行 Node Catalog admission、topology、reference 或 Agent assembly validation，但仍要求请求通过 `WorkflowGraphDocumentV1` 的基础 wire schema，包括字段类型、ID/handle 格式、`extra=forbid` 和 layout 数值约束；基础 schema 失败仍返回 422。保存成功会原子设置 `enabled=false`，使已 enabled 的 Workflow 立即退出 `/v1/models` 和 child target 集合。Workflow domain 不设置 Node count、Edge count 或 document size quota；基础 HTTP、内存、
磁盘和 SQLite 仍可能按真实资源情况失败。

【`PUT /graph`】执行完整 static validation：wire、Node type/version/config、role、handle、Edge、topology、Command/Task Dispatcher reference 和 Main Agent assembly，以及 Command/Task Dispatcher 独占 Python package 的 folder、manifest、entry file 和 static adapter contract。正式 Graph 恰有一个 Start 和一个 End，且 Start 至少有一条合法 outgoing Edge；`Start -> End` 合法。editor 通过 `/validate` 预先显示全部 issue，并在存在 error、validation 尚未完成或 validation request 失败时禁用 `PUT /graph`；请求失败会显示独立的 retry validation 操作。backend 在 PUT 时重复相同 validation，
不存在绕过入口。save 失败不写 candidate Graph，也不改变原 `enabled` state。

`admit_workflow_document()` 和 `validate_workflow_executable()` 执行 static validation。完整的 `/validate` 与 `PUT /graph` 通过 `workflow_executable_report()` 在 admission 和 topology 之上组合 reference、package resource 与 static Agent assembly check；该阶段只读取和扫描配置资源。
`GET /api/validation/repository` 对整个 configuration repository 执行 validation，也不代替一次真实 Workflow invocation。

AI 通过 management FastAPI 调用 `/validate` 时能直接读取完整 structured issue。响应包含 `valid`、`stage` 和 `issues[]`；每个 issue 提供 `code`、`scope`、`severity`、`path`、`owner_id`、`owner_name`、`message_key`、`message_args` 和可读 `message`，有具体归属类型时还包含 `owner_type`。响应会一次返回全部 issue；`severity=error` 使 `valid=false`，warning 允许继续 `PUT /graph`。请求失败时保持 candidate Graph，修复 Edge 或 service state 后显式重试 `/validate`。

Workflow metadata PUT 只更新 name、role 和 runtime limits，并保留当前 `enabled`；只有正式 Graph PUT 可以 enable，draft PUT 可以 disable。

## Node 和 Edge 规则

以 `GET /api/workflow-node-catalog` 为当前事实。现有 Node 如下：

本节代码分成两类信息：function signature、return field、Edge key 和 validation boundary 是固定 contract；State/Runtime source、业务 rule、State update 和 task 划分是建议示例。具体选择来自当前 Workflow 的真实 data flow。

| Node | `config` | input -> output | 是否写 script |
| --- | --- | --- | --- |
| `start` | `{}` | none -> `next` | 否；直接映射 LangGraph `START` |
| `agent` | `main_agent_id`, `defer` | `in` -> `next` | Node 本身不写；行为来自 Main Agent、WIC 和 component |
| `command` | `command_id` | `in` -> `branch` | 是；component 提供 `create_command()` |
| `task-dispatcher` | `task_dispatcher_id` | `in` -> `dispatch` | 是；component 提供 `create_dispatcher()` |
| `end` | `{}` | `in` -> none | 否；直接映射 LangGraph `END` |

`agent.in` 接受 normal、branch 和 dispatch Edge；`command`、`task-dispatcher` 与 `end` 的 `in` 接受 normal 或 branch。dispatch Edge 的目标是 Agent，且同一个 Agent 的入边统一使用 dispatch 或 normal/branch 语义。

AI 构造 Graph 时可按以下顺序组织；visual layout 不承载 execution semantics：

1. 从 Catalog 选择 Node type/version，并严格按 `config_schema` 填 config。正式 Graph 恰有一个 system `start` 和一个 system `end`；
   不从 component library 添加、复制或删除这两个 system Node。
2. 给每个业务 Node 分配全图唯一、稳定的 `id`。Node 与 Edge ID 都以字母开头，只使用字母、数字、`_`、`-`，最长 64 字符；`source_handle` 和 `target_handle` 以小写字母开头，只使用小写字母、数字和 `-`，最长 64 字符。
3. control flow 决定 execution relationship，layout 只描述位置。Start 至少连接一条合法 outgoing Edge；除 system End 外，每个正式 Node 都从 Start 可达；End 自身允许没有 incoming Edge。
4. 每条 Edge 从 source Catalog output handle 指向 target 接受该 type 的 input handle。Edge `id` 同样唯一，两端 handle 都是 wire field。
5. 来源 handle 决定协议：`next` 是 normal，`branch` 是 branch，`dispatch` 是 dispatch；wire 没有额外 `edge_type`。
6. fan-out、fan-in、Command `branch_key`、Task Dispatcher `dispatch_key`、leaf 和 loop exit 构成 `/validate` 前的 structure check。移动 Node、color 和 Vue Flow
   renderer field 都不会改变 execution semantics。

canvas color、class、marker 和 animation 只是 Vue Flow projection，不进入 Graph document，也不改变 LangGraph scheduling。

Node 执行工作并返回 State update；Edge 表达 activation。Command/Task Dispatcher script 只返回业务 key、task 和 update，不读取 Edge ID、target Node ID、
layout 或完整 topology。多个 single-responsibility Node + Edge 可以分别表达业务处理、routing、wait 和 termination semantics。

普通 Agent/Start 使用 static Normal Edge。condition 和 successor selection 全部由 Command Node 完成，其 output 使用 Branch Edge；Graph 只声明 candidate target。Task Dispatcher 专门生成并 dispatch task，其 output 使用 Dispatch Edge。Command/Task Dispatcher 没有 normal output handle，
其 script 返回由 Shell 映射到 LangGraph `Command`/`Send` 的领域 contract。

## Command Node

`GET /api/python-package-templates/command` 返回 `内置示例-rule-based-command` 的当前 revision 和 source，可作为按业务改写的起点；本文代码展示调用 contract。

Graph Node 只引用 component UUID：

```json
{
  "id": "decision",
  "type": "command",
  "type_version": 1,
  "config": {"command_id": "<command UUID>"}
}
```

固定 contract 是 synchronous factory 和 return structure；下面的 field、condition 和 State update 只是可替换示例：

```python
def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        branch = "review" if shared_vars.get("requires_review") is True else "continue"
        return {
            "activate": [branch],
            "update": {"shared_vars": {"last_route": branch}},
        }

    return command
```

Graph 中对应 candidate Branch Edge 的 wire 为：

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

如果 script 可能返回 `continue`，再连接一条 `branch_key: "continue"` candidate Branch Edge。`command` 可以按场景读取完整 `state`、
`runtime.context` 和 `runtime.store`；示例从 `shared_vars.requires_review` 读取业务 input。`activate` 可以返回零个、一个或多个不同 key；为空或省略时只提交 `update`，当前 path 在该 Node 自然结束。`if/elif/else`、`match` 和业务 key 由 script 负责。非空 key 与同源 Branch Edge 完全匹配，未知 key 使本次 Run 受控失败。`update` 可以更新当前 Workflow State 已声明的任意 top-level channel，空更新使用 `{}`。script 返回 Agent Shell contract，由 runtime 映射为 LangGraph `Command` 和目标 Node。

## Task Dispatcher

`GET /api/python-package-templates/task-dispatcher` 提供 `内置示例-item-list-dispatcher` 的当前 revision 和 source，再按实际 task source 改写；示例使用 `items` 字段。

Graph Node 同样只引用 component UUID：

```json
{
  "id": "dispatcher",
  "type": "task-dispatcher",
  "type_version": 1,
  "config": {"task_dispatcher_id": "<task-dispatcher UUID>"}
}
```

固定 contract 同样是 synchronous factory 和 return structure。下面用 `shared_vars.items` 演示一种 source，不代表 Task Dispatcher 只能读取该 field：

```python
def create_dispatcher():
    async def dispatch(state, runtime):
        items = state.get("shared_vars", {}).get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("shared_vars.items must be a non-empty list")

        tasks = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("each item must contain a stable string id")
            tasks.append(
                {
                    "task_id": f'item:{item["id"]}',
                    "dispatch_key": "item",
                    "payload": {"item": item},
                }
            )

        return {
            "tasks": tasks,
            "update": {"shared_vars": {"dispatched_count": len(tasks)}},
        }

    return dispatch
```

Graph 中对应的 Dispatch Edge 使用 `source_handle: "dispatch"` 和 `dispatch_key: "item"`。`dispatch` 可以按业务需要从完整 `state`、
`runtime.context` 或 `runtime.store` 选择 task；task source、granularity、target key、payload 和 parent State `update` 都由当前 Workflow 决定。当前 contract 接受每次 invocation 产生的至少 1 个 task，且不设置产品数量上限；`task_id` 在本 batch 唯一并来自 stable business identity；`payload` 是 strict JSON object；
`update` 可以更新任意已声明的 top-level State channel。script 不 import 或返回 `Send`。

当前 contract 不接受空 `tasks`；如果数据可能为空，建议由 upstream Command Node 绕过 Task Dispatcher。Agent Shell 会为每个 worker 注入独立 `workflow_task`，target Agent 是否读取、如何转换以及加入哪些 task field，仍由该 Agent 的 WIC 决定。

## Agent、Start 和 End

Agent Node 没有 Node script。它只引用完整 Main Agent。需要改变 input 时写 WIC；需要调用 external capability 时配置 Tool；需要改变 Model call 前后行为时使用 LangChain Middleware，同步 delegation 由 Subagent 提供。canvas Agent Node 本身没有额外的 Agent script layer。

Agent 成功后，完整 reduced messages 写入 Lifecycle Store，parent State 只保留 `agent_invocations` reference。successor Agent 不会自动继承 earlier messages；其 WIC 通过选择 causally visible invocation，再按 `result_ref` 从 Store 读取 artifact。

Start/End 没有 script、configuration 或 business data transformation。Start 不把 client messages 注入 State；End 不负责自动取消 background task、删除 Lifecycle 或拼接最终 Agent content。WIC 负责 input，Main Agent 的 Agent Event Output 和可选 Workflow Event Output 负责 output。

Start 是 Graph entry，正式 Graph 恰有一个 Start 且至少有一条合法 outgoing Edge。End 是 LangGraph `END` 的显式 projection，表示一条路径的逻辑终点。End 可以没有任何 incoming Edge。普通 reachable leaf 可以自然结束；有 loop 时让 exit path 连接 End。

## Leaf、join 与 super-step

LangGraph 按 super-step 执行。同一 super-step 内所有 scheduled Node 读取同一个 boundary State snapshot；各 Node 的 update 在 boundary 由 State reducer merge，随后产生 next task。Graph 在没有 runnable task、没有待传递 message 时自然结束。

- 可达的普通 Node 可以没有 outgoing Edge。它完成 update 后成为该 path 的 leaf，其他 active branch 继续执行。
- canvas 保留唯一的 system End，但 End 可以完全没有 incoming Edge。
- 某条 path 到达 End 只终止该 path，不取消同一 super-step、其他 branch 或 background Run。
- 所有 path 的后续 task 集合为空时，整个 Graph 结束。
- loop 不等于 exit condition。loop 若始终产生 task，会一直执行到业务逻辑退出、Run timeout 或 `recursion_limit`。

normal fan-out 与 fan-in 不同：

```text
fan-out:
A -> B
A -> C

all-of:
B -> J
C -> J
```

fan-out 表示 A 完成后同时激活 B、C。普通 executable target J 的多条非 START Normal Edge 会编译为 `add_edge([B, C], J)`；只有 B、C 都完成才激活 J。若 B、C 来自 mutually exclusive branch 而本次只激活一边，J 不执行。
mutually exclusive branch 适合作为独立 leaf 或分别指向 End，不适合 join 到 all-of target。

START 使用入口激活语义：`Start -> J` 与 `Start -> A -> J` 会让 J 分别在启动时和 A 完成后各执行一次。
多条进入 End 的 Edge 也互相独立；End 不等待所有 source。需要 A、B 都完成后再 decision 时，先让两者 join 到一个 executable Node，
再由该 Node 进入 End。

Branch 只激活 `activate` 返回的 candidate key；Dispatch 只为返回的 task 创建 worker；未选择的 candidate Edge 不产生 task。

官方语义参考 [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) 和 [LangGraph super-steps](https://docs.langchain.com/oss/python/langgraph/checkpointers#super-steps)。项目内的唯一映射见 [Workflow Graph 画布契约](../../../.docs/architecture/workflow-graph-canvas-contract.md)。

## 新 Node type 的边界

新 Node type 以 LangGraph 公开的 Node/Runnable、subgraph、`Command`、`Send` 或虚拟哨兵语义为映射基础。
第二套 super-step、Edge 触发、汇聚或终止规则不属于当前架构。

Node 负责一次清晰工作以及 State/Runtime 的 read 和 update；Edge 负责 Node 之间的 activation relationship。用户 Python package 不读取 Edge ID、
target Node ID、canvas layout 或完整 topology，也不自行解释 Edge。复杂逻辑可以拆成多个 single-responsibility Node；新 Node type 对应现有 Node + Edge 无法清楚表达的官方运行范式。

下一步：[编写 Python extension](04-python-extensions.md)。
