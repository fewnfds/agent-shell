# Workflow Input Context

Workflow Input Context（WIC）是 Agent Shell 的核心上下文工程约定：它决定一次 Workflow 调用中的输入材料，如何在某个 Agent 真正启动前被选择、转换并写入该 Agent 的私有 `messages`。

WIC 不是画布 Node，也不是一类 capability 组件。当前实现是普通的 LangChain `AgentMiddleware`；Agent Shell 在 `examples/` 中提供一份只实现异步 `abefore_agent` hook 的可复制实现，
每个使用者可以从它创建独立 Custom Middleware，再直接修改自己的上下文逻辑。

## 为什么需要 WIC

客户端提交的 `messages[]` 是本次请求的不可变事实，但 Agent Shell 不把整包消息自动写入 Workflow root State。画布上的每个 Agent Node 都以自己的私有 Agent State 运行，默认输入 `messages` 为空；前序 Agent 的输出也不会自动变成后继 Agent 的对话历史。

这个边界使不同 Agent 可以针对同一请求获得不同材料：一个 Agent 可以读取完整原始任务，另一个只读取某个前序结果，
还可以加入当前 Agent Filesystem 中的任务文件或把消息身份重新组织。WIC 是执行这些选择的唯一入口，而不是外围聊天历史、
自动累积机制或隐藏的 State 同步。

```text
客户端 messages[]
        │
        ▼
Lifecycle Store（不可变请求快照） ──┐
WorkflowRuntimeContext（run/invocation 身份） ──┤
当前 Agent State 与父图快照 ───────┼── WIC abefore_agent(...) ── 当前 Agent 私有 messages
当前 Agent 的 Deep Agents Filesystem backend ─┘
```

## 输入来源

内置 WIC 示例可以在官方 Middleware hook 中组合以下数据：

- Main Agent：用 `runtime.context.lifecycle_id` 定位 `runtime.store` 中 `lifecycle_input_namespace(lifecycle_id)` / `LIFECYCLE_INPUT_KEY` 的冻结 OpenAI `system/user/assistant` 请求快照；
- Subagent：`state["messages"]` 中由 Deep Agents `task` 委派产生的私有消息，不自动附加根请求；WIC 的 `scope` 由 Shell 按 owner 类型注入为 `main_agent` 或 `subagent`，Subagent 分支默认不访问 `runtime.store`；
- 父 Workflow：`state["workflow_state_snapshot"]`，包括前序 Agent 完成后写入的
  `agent_invocations[invocation_id]` 轻量引用；完整 invocation artifact 通过 `runtime.store` 和 `result_ref` 读取；
- 当前身份：`runtime.context.lifecycle_id`、`run_id`、`thread_id`、`launcher_id`、`background_task_id`、
  `workflow_node_id`、`agent_id` 与 `invocation_id`。`launcher_id` 是后台 Run 发起者；后台 Agent 不属于画布 Node，
  因此其 `workflow_node_id` 为空；
- 当前动态任务：Task Dispatcher worker 的 `state["workflow_task"]`；普通 Agent 调用不存在该字段；
- 共享文件：工厂收到的当前 Agent 的 Deep Agents `backend`（由该 Agent 的 Filesystem capability 物化），只读取虚拟绝对路径；Workflow 本身不拥有 Filesystem；
- 当前 Agent State：hook 的 `state` 参数，以及其他 Middleware 声明的 State channel。

Lifecycle Store 中的输入记录由平台写入，WIC 只读取并复制需要的消息，再通过返回值更新 State；消息 channel 必须使用 `Overwrite(convert_to_messages(...))`，否则普通列表会触发 reducer 追加并破坏消息边界。`runtime.store is None` 或 Main Agent 的 `lifecycle_id` 为空时，读取请求快照会失败。

## Task Dispatcher worker

WIC 是任务材料的消费者，不是调度器。Task Dispatcher 先根据 Workflow State 生成任务，Shell 再通过 LangGraph `Send` 把每项任务作为私有 `workflow_task` 注入目标 Agent wrapper。worker 的 WIC 可以读取：

```python
task = state["workflow_task"]
task_id = task.get("task_id")
dispatch_key = task.get("dispatch_key")
payload = task.get("payload", {})
```

该任务不写入 Workflow root State，也不复制到 Runtime Context。任务完成后，父 State 的 `agent_invocations` 记录会携带 task identity，供下游汇总 Agent 的 WIC 选择。WIC 中的列表扫描不构成任务抢占或计数锁；同一 super-step 的并行 worker 读取同一个父 State 深拷贝快照，各自带不同的 `workflow_task` 与 `invocation_id`，不是实时租约系统。

## 从内置示例创建

1. `GET /api/python-package-templates/middleware` 获取当前 catalog revision。
2. 选择 `key=="内置示例-workflow-input-context"`，通过【代理组件 / 自定义 Middleware】或 `POST /api/blocks/custom-middleware` 新建配置，并提交 `python_package: {"folder":""}` 与 `python_package_template: {"key":"内置示例-workflow-input-context","revision":"<catalog revision>"}`。
3. 保存后编辑当前配置独占的 `main.py`。
4. 在 Main Agent 或 Subagent 的有序 `middleware_refs` 中选择该配置。

内置示例源码位于：

```text
examples/agent-components/custom-middleware/workflow-input-context/
```

它只是创建配置时的只读来源。保存后，系统会像其他 Custom Middleware 一样复制成配置独占的 Python 包；之后修改示例不会改变已经创建的 WIC。用户模板可以同样命名，页面使用 `内置示例-` 前缀区分两个来源。

## 集中变化函数

示例把当前 Workflow 的业务选择集中在异步函数 `async def build_workflow_input_messages(state, runtime, request_messages, backend) -> list[dict]`。`load_invocation_artifact` 与它都必须 `await`。默认实现只是建议起点：复制并校验原始请求消息，
并在当前 State 存在 `workflow_task` 时追加一条 task 消息。可以删除、替换或扩展这些步骤。

这个函数已经拿到选择上下文所需的入口：

- `request_messages`：Main Agent 的原始请求消息；
- `state`：当前 Agent 私有 State 和父图快照；
- `runtime.context` / `runtime.store`：当前身份、Lifecycle 数据和 invocation artifact；读取 artifact 需要同时使用 `runtime.context.lifecycle_id` 与 `run_id` 定位 invocation namespace；
- `backend`：当前 Agent 的 Filesystem backend，可按虚拟路径读取文件；`workflow_state_snapshot` 不包含 `files`，文件必须通过 backend 读取。

示例保留 `load_invocation_artifact(runtime, record)` 帮助函数。前序结果通过父图快照中的明确 invocation 记录加载完整 artifact；所有前序输出不会自动拼接。文件读取、消息 role 变换、裁剪和排序没有固定 schema，由当前 Agent 的职责决定。

项目不定义更多 WIC 变种 schema。选择哪个前序 invocation、保留哪些原始消息、如何分配 role、是否加入文件以及如何截断，
都由当前 Middleware 的 Python 代码决定。多个 WIC 变种也只是多个普通 Middleware 配置。

## 顺序

WIC 没有专用装配槽位，也没有 Agent Shell 管理的固定相对顺序。Main Agent 和 Subagent 分别通过自己的 `middleware_refs` 决定 Custom Middleware 实例顺序。LangChain 对 `before_*` hook 按列表正序、`after_*` hook 按逆序、`wrap_*` 按列表嵌套执行；因此，如果多个 Middleware 都会改写 `messages`，后面的 `before_*` hook 会看到前面已经返回的 State。若覆盖同步 hook，必须同时提供对应异步 hook，否则 Agent Shell 在装配期以 422 拒绝。WIC 代码不负责寻找或调用其他 Middleware。

## 边界

- WIC 只构造当前 Agent invocation 的私有上下文，不修改客户端请求快照；
- Store 保存 Lifecycle 内跨 Run 公共事实，Runtime Context 只保存当前 Run/Invocation 的不可变身份，Graph State
  继续保存参与路由、reducer 与 checkpoint 的变化数据；
- Workflow root State 不保存整包输入，也不会自动累积成产品聊天历史；WIC 不得把客户端请求快照写入 root State 或跨运行累积为聊天历史；
- 前序 Agent 输出经由 `agent_invocations` 中因果可见的引用从 Store 读取 artifact，mapping 插入顺序没有因果语义；
- 同一画布节点再次执行会产生新的 invocation ID，节点身份或明确 ID 用于选择记录；
- Subagent 默认保留 delegated messages，是否加入根请求由该 Subagent 的 WIC 决定；
- 文件路径属于当前 Agent 的虚拟 Filesystem，不接受宿主绝对路径；
- Custom Middleware 是受信任的服务端 Python 代码，不在 sandbox 中运行；Provider secret view 不属于 WIC 输入，不得把 secret 复制进 State、checkpoint 或其他持久化数据。

LangChain 官方机制可参考 [Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) 和[Runtime context](https://docs.langchain.com/oss/python/langchain/runtime#inside-middleware)。Python 包目录、依赖、复制和运行边界见[文件化 Python 扩展](middleware-packages.md)。
