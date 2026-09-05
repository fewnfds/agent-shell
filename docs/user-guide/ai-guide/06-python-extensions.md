# 编写 Python extension

本章说明五类 Python-backed Component 共用的 package 生命周期、dependency 与 runtime 边界，并给出 Command 和 Event Output 的 callable contract。

Python extension 在 Agent Shell service process 的 trusted boundary 中执行，没有 sandbox。扩展使用 LangChain、LangGraph 和 Deep Agents public API。

## 1. 选择 extension type

Custom Tool：让模型在 Agent loop 中选择并调用能力。固定 entry 是同步 `create_tool()`，返回一个 LangChain `BaseTool`。完整说明见[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。

Custom Middleware：在 Agent lifecycle、model call 或 Tool call 周围增加行为。模块提供同步 `create_middleware(...)` factory，返回一个 `AgentMiddleware`。factory 可以按参数名请求当前可用的构造数据，或使用 `**kwargs` 接收全部可用值。hook 与 ordered ref 见[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。

Command：执行确定性 State transition、Branch Edge selection 和运行时 Agent task dispatch。同步 `create_command()` 返回 async Node callable。

Agent Event Output：过滤和渲染 Agent event。同步 `output(event, origin)` 返回 `str`。

Workflow Event Output：过滤和渲染 Workflow-owned event。同步 `output(event, origin)` 返回 `str`。

各接口的行为 owner：

- State update 属于 Node、Tool 或 Middleware contract；
- successor selection 属于 Command；
- 公开文本 projection 属于 Event Output；
- long-lived artifact 属于 Store 或 Filesystem。

State persistence、routing 和 output projection 分别通过对应 contract 生效。

## 2. 创建和编辑闭环

```text
读取 template catalog
  -> 用 key + revision 创建 Component
  -> GET 私有 Python package projection
  -> 编辑 source 和 local module
  -> 根据真实 import 编辑 requirements.txt
  -> requirements 变化时 restart service
  -> GET package 并检查 dependency_status
  -> repository 和 Graph validation
  -> 真实 invocation
```

具体步骤：

1. 调用对应的 `GET /agent-shell/api/python-package-templates/{kind}`；
2. 从当前 response 选择精确 `key` 和 `revision`；
3. POST 创建 Component，并保存 UUID；
4. 调用 `GET /agent-shell/api/blocks/{type}/{id}/python-package`；
5. 从 response 确认私有 folder、manifest、entry file、file path 和 revision；
6. 通过 File Manager API 或用户授权的本地编辑器修改该私有 package；
7. 只为 source 直接 import 的额外 third-party package 声明 dependency；
8. `requirements.txt` 变化后重启 service；
9. 再次 GET package，确认 dependency status；
10. validation 通过后发起一次真实 Workflow invocation。

## 3. 从 template 创建 Component

Python-backed Component 使用统一创建形状：

```http
POST /agent-shell/api/blocks/<component type>
```

```json
{
  "name": "<component name>",
  "python_package": {
    "folder": ""
  },
  "python_package_template": {
    "key": "<catalog key>",
    "revision": "<catalog revision>"
  }
}
```

Component type 与 template kind 的常用对应关系是：

- `custom-tool` 使用 `custom-tool` template；
- `custom-middleware` 使用 `middleware` template；
- `agent-event-output` 使用 `agent-event-output` template；
- `workflow-event-output` 使用 `workflow-event-output` template；
- `command` 使用 `command` template。

以当前 Catalog 和 endpoint response 为准。不要根据这个列表构造当前实例不存在的 type。

首次保存后，系统把 template 复制到以 Configuration 名称命名、由该 Configuration UUID 独占的 private package。一个 Configuration 不引用另一个 Configuration 的 package directory。

`package.json.id`、folder 和 adapter 必须与 owner Configuration 一致。不要移动或重命名受管 extension directory。

## 4. 编辑 package

`GET /agent-shell/api/blocks/{type}/{id}/python-package` 递归返回 package file 和真实 File Manager path。根据 response 编辑 `main.py`、local module 和 `requirements.txt`。

local module 使用普通 relative import，例如：

```python
from .helpers import build_tasks
```

Python source change 在下一次 request materialization 时重新加载。`requirements.txt` change 在 service restart 后生效。

文件 revision 已变化时，旧 revision 的保存会被拒绝。重新读取当前内容，合并用户草稿，再显式保存。不要用旧 projection 覆盖并发修改。

完整 package、manifest 和 File Manager 规则见[文件化 Python 扩展](../middleware-packages.md)。

## 5. Construction stage 和 runtime stage

factory 在 Agent 或 Graph materialization 时运行，只负责创建 callable 或 Middleware object。

Runtime callable 在 Node、Tool 或 Agent hook 真正执行时运行，才拥有 State、Runtime Context、Store 和 stream writer。下一节的 Command 示例展示这两个阶段的边界。

`create_tool()`、`create_command()` 和 `create_middleware(...)` 中没有某次 invocation 的 Runtime。

需要 `runtime.context`、`runtime.store`、`ToolRuntime` 或 `get_stream_writer()` 的代码必须放在对应 runtime callable 或 Middleware hook 中。

### Async 与阻塞 I/O

函数是否声明为 `async def` 取决于调用 contract；不需要把所有 extension 函数改成 async。运行边界按代码实际所在的执行位置判断：

- `command(state, runtime)` 和 Middleware async hook 位于共享事件循环。网络、数据库、文件和子进程操作使用对应 async API；同步库没有 async API 时，只把具体阻塞调用放入 `await asyncio.to_thread(...)`。
- 同步 LangChain Tool 可以保留同步 callable；Agent Shell 使用官方 `BaseTool.ainvoke()` 路径，LangChain 在线程执行默认同步 `_run()`。Tool 自己提供 async coroutine 时，该 coroutine 同样不得直接阻塞。
- `output(event, origin)`、`segment_end(event, origin)` 和 `run_output(event, origin)` 是逐事件调用的同步内存 projection。它们应只做短小解析和字符串生成，不读取文件、不访问网络或数据库，也不启动子进程。
- 同步 factory 和 module import 由平台在 construction stage 隔离，但 factory 仍只负责对象装配，不承载 invocation 工作。
- CPU 密集任务使用独立进程或外部执行器；线程隔离只解决无法异步化的阻塞 I/O。

开发启动启用 LangGraph Dev 的阻塞检测。检测到 async 执行边界中的同步阻塞调用时，当前 Run 会失败并产生诊断；不要用全局放行参数隐藏问题。

## 6. Command contract

Command Component 的 factory 是同步函数：

```python
def create_command():
    async def command(state, runtime):
        shared_vars = state.get("shared_vars", {})
        branch = "review" if shared_vars.get("requires_review") else "continue"
        items = shared_vars.get("items", [])
        tasks = [
            {
                "task_id": f'item:{item["id"]}',
                "dispatch_key": "item",
                "payload": {"item": item},
            }
            for item in items
        ]
        return {
            "activate": [branch],
            "dispatch": tasks,
            "update": {
                "shared_vars": {
                    "last_route": branch,
                    "dispatched_count": len(tasks),
                }
            },
        }

    return command
```

系统约束：

- factory 返回 async callable；
- callable 接收完整 Workflow `state` 和 LangGraph `runtime`；
- `activate` 是零个、一个或多个 Branch Edge key；
- `dispatch` 是零个、一个或多个 Agent task；
- `update` 是当前 Workflow State 的 partial update；
- Branch 和 Dispatch 可以在同一次 invocation 中同时产生；
- 非空 activate key 必须与同源 Graph `branch_key` 完全匹配；
- 每个 `dispatch_key` 必须与同源 Dispatch Edge 完全匹配，Dispatch Edge 的 target 必须是 Agent Node；
- `task_id` 长度为 1 至 128 个字符，在当前 Command invocation 中唯一，并建议来自稳定业务 identity；
- `dispatch_key` 长度为 1 至 64 个字符；
- `payload` 是 strict JSON object，数值必须是有限数；
- package 不读取 Edge ID、target Node ID、layout 或完整 topology；
- package 不 import 或直接返回 LangGraph `Command`/`Send`。

compiler 把结果映射为一个 LangGraph `Command`：每个 activate key 选择一个 Branch target，每个 dispatch item 构造一个 `Send`。同一 Dispatch Edge 可以由多项选择，使同一个 Agent Node 获得多次独立 invocation。每个 worker 的 private `workflow_task` 包含 `command_node_id`、`command_invocation_id`、`task_id`、`dispatch_key` 和 `payload`。

同批 parent `update` 不自动成为这些 `Send` 的私有 input。worker 当批需要的材料放入 `payload`，大型材料保存到 Store 或 Filesystem 并通过 payload 传递 reference。业务字段、condition、key、task 和 update shape 根据当前 design record 修改。

## 7. Custom Tool 和 Middleware

Custom Tool 固定使用同步无参 `create_tool()`，返回一个 `BaseTool`。LangChain `@tool` 的 function name、description 与 typed parameters 形成模型可见 Tool contract。

Tool invocation 的 Runtime 通过 Tool callable 的 `ToolRuntime` 注入参数取得。`create_tool()` 属于 construction stage。

Custom Middleware factory 返回官方 `AgentMiddleware`。运行能力位于 `before_agent`、`before_model`、`wrap_model_call`、`wrap_tool_call` 等官方 hook 中。

Agent Shell 使用 async Agent execution path；同步 hook 需要对应 async hook。Main Agent 与 Subagent 分别通过 ordered `tool_refs` 和 `middleware_refs` 装配这些配置。

代码、API shape、排序、AAP、Runtime 与装配示例见[编写 Agent Tool、Middleware 与 hook](04-agent-tools-middleware-hooks.md)。使用 Middleware 改写 Agent 初始消息时同时阅读[Agent Additional Prompt](../agent-additional-prompt.md)。

## 8. Event Output contract

Agent Event Output 和 Workflow Event Output 的 protocol entry 都是同步双参数函数：

```python
def output(event, origin):
    if event.get("method") != "messages":
        return ""
    params = event.get("params", {})
    data = params.get("data") if isinstance(params, dict) else None
    if isinstance(data, (list, tuple)) and len(data) == 2:
        payload = data[0]
        if isinstance(payload, dict) and payload.get("event") == "content-block-delta":
            delta = payload.get("delta")
            return str(delta.get("text", "")) if isinstance(delta, dict) else ""
    return ""
```

系统约束：

- `output(event, origin)` 必须返回 `str`；
- `event` 是 LangGraph v3 原始 ProtocolEvent，`origin` 只保存 Agent Shell Lifecycle/Run/Workflow/Node/Agent 身份；
- 读取 channel-specific payload 前先判断 `event["method"]`；
- `messages`、`tools`、`custom`、`values`、`updates`、`tasks`、`input`、`lifecycle` 等官方 channel 原样传递；
- 空字符串只过滤公开渲染文本；
- Event Output 不更新 State、不选择 successor，也不处理顶层 HTTP error。

Shell 合成的 Run 状态不是 ProtocolEvent。Workflow Event Output 可选提供同步 `run_output(run_event, origin)`，只处理 `type="agent_shell.workflow_run"` 的产品状态；Agent Event Output 只处理 raw ProtocolEvent。

Agent Event Output 处理 Agent-owned event。Workflow Event Output 处理 Workflow-owned non-Agent event。

稳定 event field 和示例见[Agent Event Output](../../wizard-pages/agent-event-output-config.md)与[Workflow Event Output](../../wizard-pages/workflow-event-output-config.md)。

## 9. 从 Workflow Node 写出 custom event

Command 的 runtime callable 可以使用 LangGraph public stream writer：

```python
from langgraph.config import get_stream_writer

get_stream_writer()("Command selected branch review.\n")
```

只在 `command(state, runtime)` 等 runtime callable 内获取 writer。不要在 module top level、factory 或 `output(event, origin)` 中调用。

这些数据在 LangGraph v3 stream 中成为 `custom` event。Command 属于 Workflow，因此需要 Workflow 引用 Workflow Event Output，并由其 `output(event, origin)` 的 `custom` branch 返回非空字符串，才会进入 OpenAI response。

Agent Node 内 Tool 或 Middleware 写出的 `custom` event 使用该 Agent 的 Agent Event Output projection。

event 是单向 output。Node 不会收到 projection result。

## 10. Dependency

Python 3.12 standard library 可以直接 import。使用 standard library 能完成任务时，不增加 third-party dependency。

平台公开 contract 中明确展示的 LangChain、LangGraph、Deep Agents 和 `agent_shell` helper 可以按当前 locked version 使用。

其他 third-party package 必须在当前 extension 自己的 `requirements.txt` 中声明 direct dependency。不要依赖核心 runtime 偶然安装的 transitive dependency。

`requirements.txt` 使用普通 PyPI requirement。URL、local path 和安装后产生不受支持 `.pth` 的 dependency 会被拒绝。uv 优先使用兼容 wheel，没有 wheel 时尝试 source build；需要 compiler 或 system library 时由实例维护者提供。额外 package 还必须支持内置 CPython 3.12、Windows x64 和平台核心约束。

Management API 没有 enumerate-all-importable-modules endpoint。不能仅凭模型记忆声称某个 package 已安装。

读取 package projection 中的：

- `dependency_status: "ready"` 表示当前 requirement 已准备完成，或没有额外 dependency；
- `dependency_status: "restart_required"` 表示 requirement 已变化，需要 restart；
- `dependency_status: "failed"` 表示 dependency preparation 失败，需要结合 `dependency_error_code` 修正；
- `requirements_fingerprint` 表示当前 dependency declaration identity。

dependency collection 只覆盖 enabled Workflow 可达的 Python-backed Component。因此最终证据是 publish、restart、package GET 和真实 invocation 的闭环。

## 11. Official capability discovery

需要当前指南未展开的 LangChain、LangGraph 或 Deep Agents public capability 时：

1. 从本章确认 script entry 和 runtime stage；
2. 从 `docs/development-and-release.md` 确认 locked version；
3. 使用已注册的 `langchain-docs` MCP 按 public type 和目标动作查询官方文档；
4. 对照 Agent Shell source、contract 或稳定测试，确认该 capability 在当前 entry 中可达；
5. 用 dependency status 和一次真实 Workflow invocation 证明当前实例可运行。

官方 type 提供但 Agent Shell 未接入产品 wire 的功能，不自动成为 Agent Shell 配置能力。

## 12. 本章完成结果

返回 Graph 或 validation 前确认：

- extension type 与行为 owner 一致；
- Component 来自当前 template `key + revision`；
- 编辑的是以 Configuration 名称命名、由该 Configuration UUID 独占的 package；
- factory 只负责 construction；
- Runtime access 位于 runtime callable 或 hook；
- routing key 与 Graph Edge key 一致；
- State update、routing 和 output projection 各自遵循自己的 contract；
- source 只使用 public API；
- 每个直接 import 的额外 third-party package 都声明在自己的 `requirements.txt`；
- requirement 变化后已 restart，并确认 dependency status；
- Graph draft 已使用最新 Component UUID 和 key 重新保存。

需要从 current Run 启动独立 Workflow Run 时阅读[跨 Workflow Run 调用](07-cross-workflow-runs.md)。随后阅读[验证、运行与交付](08-validate-run-deliver.md)。
