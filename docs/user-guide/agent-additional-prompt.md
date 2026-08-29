# Agent Additional Prompt

Agent Additional Prompt（AAP）是 Agent Shell 推荐的 Agent 初始提示词注入范式。AAP 以普通 LangChain `AgentMiddleware` template 提供，使用异步 `abefore_agent` hook，在一次 Agent invocation 启动前构造该 Agent 私有的标准 multi-turn `messages[]`。

需要这项能力的 Main Agent 或 Subagent 从内置 template 创建独立 Custom Middleware，并通过自己的有序 `middleware_refs` 装配。`middleware_refs` 可以为空；每个 Agent 根据职责独立决定是否使用 AAP 以及使用哪份配置。

## 适用场景

客户端提交的 `messages[]` 作为 current request 的不可变事实保存在 Lifecycle Store。canvas Agent Node 以空 `messages` 启动自己的 Agent graph；synchronous Subagent 接收 Deep Agents delegation 产生的私有消息。AAP 可以在 Agent 启动前选择、转换并编排以下材料：

- current Lifecycle 的 request `messages[]`；
- Command Dispatch 注入当前 Agent 的 `workflow_task`；
- parent Workflow State snapshot 中因果可见的 upstream invocation reference；
- Runtime Context 与 Store 中 current invocation 可访问的数据；
- current Agent Filesystem backend 中的任务文件；
- current Agent State 与其他 Middleware 声明的 State channel。

不同 Agent 可以获得不同的初始提示词。一个 Agent 可以接收完整 request，另一个可以只接收 current task payload、某个 upstream result 或一组文件材料。

```text
客户端 messages[]
        │
        ▼
Lifecycle Store（不可变请求快照） ─────────┐
WorkflowRuntimeContext（run/invocation 身份） ──┤
current Agent State 与 parent Graph snapshot ─┼── AAP abefore_agent(...) ── current Agent private messages
current Agent 的 Deep Agents Filesystem backend ──┘
```

## 输入来源

内置 AAP template 演示以下入口：

- Main Agent：用 `runtime.context.lifecycle_id` 定位 `runtime.store` 中 `lifecycle_input_namespace(lifecycle_id)` / `LIFECYCLE_INPUT_KEY` 的冻结 OpenAI `system/user/assistant` 请求快照；
- Subagent：读取 `state["messages"]` 中由 Deep Agents `task` delegation 产生的私有消息；Shell 按 owner 类型把 `scope` 注入为 `main_agent` 或 `subagent`；
- parent Workflow：读取 `state["workflow_state_snapshot"]` 中的 `agent_invocations[invocation_id]` 轻量 reference，再通过 `runtime.store` 和 `result_ref` 加载完整 invocation artifact；
- 当前身份：读取 `runtime.context.lifecycle_id`、`run_id`、可空 `checkpoint_thread_id`、`launcher_id`、`background_task_id`、`workflow_node_id`、`agent_id` 与 `invocation_id`；
- 当前动态任务：读取 Command-dispatched Agent 的 `state["workflow_task"]`；
- 共享文件：使用工厂收到的 current Agent Deep Agents `backend`，按虚拟绝对路径读取；
- current Agent State：使用 hook 的 `state` 参数以及其他 Middleware 声明的 State channel。

Lifecycle Store 中的输入记录由平台写入。AAP 读取并复制 current Agent 所需的消息，再通过 Middleware State update 注入 Agent。更新 `messages` channel 时使用 `Overwrite(convert_to_messages(...))`，避免普通 list update 触发 reducer 追加并破坏本次 invocation 的初始消息边界。读取 Main Agent 请求快照需要可用的 `runtime.store` 和 `runtime.context.lifecycle_id`。

## Command Dispatch task

Command 根据 Workflow State 生成任务，Shell 通过 LangGraph `Send` 把每项任务作为私有 `workflow_task` 注入 target Agent wrapper。AAP 可以读取该任务并编排 Agent 的初始提示词：

```python
task = state["workflow_task"]
task_id = task.get("task_id")
dispatch_key = task.get("dispatch_key")
payload = task.get("payload", {})
```

任务保存在 target 的 private Agent State。任务完成后，parent State 的 `agent_invocations` record 携带 task identity，供 downstream aggregation Agent 的 AAP 选择。同一 Super-step 的并行 Agent 读取同一个 parent State 深拷贝 snapshot，各自带不同的 `workflow_task` 与 `invocation_id`。

## 从内置 template 创建

1. `GET /api/python-package-templates/middleware` 获取当前 catalog revision。
2. 选择 `key=="内置示例-agent-additional-prompt"`，通过【代理组件 / Custom Middleware】或 `POST /api/blocks/custom-middleware` 新建配置，并提交 `python_package: {"folder":""}` 与 `python_package_template: {"key":"内置示例-agent-additional-prompt","revision":"<catalog revision>"}`。
3. 保存后编辑 configuration-owned Python package 中的 `main.py`。
4. 在需要 AAP 的 Main Agent 或 Subagent 的有序 `middleware_refs` 中选择该配置。

内置 template 源码位于：

```text
examples/agent-components/custom-middleware/agent-additional-prompt/
```

该目录是创建配置时的只读来源。保存后，系统将 template 复制为配置独占的 Python package；每个配置分别维护自己的提示词逻辑。模板选择器使用 `内置示例-` 前缀区分仓库内置示例与用户模板。

## 集中变化函数

示例把 Agent 的材料选择集中在 async function `async def build_agent_additional_prompt_messages(state, runtime, request_messages, backend) -> list[dict]`。`load_invocation_artifact` 与它都需要 `await`。建议起点会复制并校验原始 request messages，并在 current State 存在 `workflow_task` 时追加一条 task message；每份配置可以删除、替换或扩展这些步骤。

这个函数具有以下入口：

- `request_messages`：Main Agent 的原始请求消息；
- `state`：current Agent private State 和 parent Graph snapshot；
- `runtime.context` / `runtime.store`：当前身份、Lifecycle 数据和 invocation artifact；读取 artifact 时同时使用 `runtime.context.lifecycle_id` 与 `run_id` 定位 invocation namespace；
- `backend`：current Agent 的 Filesystem backend，可按虚拟路径读取文件；文件内容通过 backend 读取。

示例保留 `load_invocation_artifact(runtime, record)` helper。upstream result 通过 parent Graph snapshot 中明确选择的 invocation record 加载完整 artifact。文件读取、message role、裁剪和排序由 current Agent 的职责决定。

## Middleware 顺序

Main Agent 和 Subagent 分别通过自己的 `middleware_refs` 决定 Custom Middleware 实例顺序。LangChain 对 `before_*` hook 按列表正序、`after_*` hook 按逆序、`wrap_*` 按列表嵌套执行。多个 Middleware 修改 `messages` 时，后面的 `before_*` hook 会看到前面已经返回的 State。覆盖同步 hook 时同时提供对应异步 hook，满足 Agent Shell 的异步运行装配 contract。

## 运行边界

- AAP 构造 current Agent invocation 的私有初始提示词，客户端请求快照保持不可变；
- Store 保存 Lifecycle 内跨 Run 公共事实，Runtime Context 保存 current Run/Invocation 的不可变身份，Graph State 保存参与 routing 与 reducer 的运行数据；Workflow 启用 Checkpointer 时，Graph State 同时进入 checkpoint；
- upstream Agent 输出通过 `agent_invocations` 中因果可见的 reference 从 Store 读取 artifact，mapping 插入顺序不承载因果语义；
- 同一 canvas Node 再次执行会产生新的 invocation ID，选择 upstream result 时使用明确的 Node、task 或 invocation identity；
- Subagent template 默认保留 delegated messages，是否加入 root request 由该 Subagent 的 AAP 配置决定；
- 文件路径使用 current Agent 的虚拟 Filesystem 路径；
- Custom Middleware 以服务进程权限执行，secret 保持在对应 Provider/Environment owner 中。

LangChain 官方机制参考 [Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) 和 [Runtime context](https://docs.langchain.com/oss/python/langchain/runtime#inside-middleware)。Python package 目录、依赖、复制和运行边界见[文件化 Python 扩展](middleware-packages.md)。
