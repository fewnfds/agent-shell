# 编写 Agent Tool、Middleware 与 hook

本章说明 Main Agent 和 Subagent 怎样装配配置独占的 Custom Tool 与 Custom Middleware，以及这些 Python package 怎样进入 Deep Agents 的 model-tool loop。

完成结果是已经创建、编辑并装配到目标 Agent 的 Tool 或 Middleware，并且对应代码路径经过 validation 和真实 invocation。

## 1. 装配关系

Main Agent是独立root graph。直接请求或Workflow Command启动其Run时，request materialization加载自己的Custom Tool、Custom Middleware和direct Subagent：

```text
Main Agent root graph
       -> ordered tool_refs
            -> create_tool() -> BaseTool
       -> ordered middleware_refs
            -> create_middleware(...) -> AgentMiddleware
       -> direct Subagent
            -> its own ordered tool_refs
            -> its own ordered middleware_refs
       -> ordered AsyncSubAgent references
            -> official async task tools
```

Main Agent 和 Subagent 分别维护 `tool_refs` 与 `middleware_refs`。这两个列表独立于 `capability_refs` 和 Subagent capability override。每个 reference 指向当前 Configuration Repository 中一份配置独占的 Python package。

## 2. 代码入口

| 入口 | 执行位置 | 返回对象或行为 |
| --- | --- | --- |
| Custom Tool | model 选择 Tool 后执行 | `create_tool()` 返回一个 `BaseTool` |
| Custom Middleware | Agent lifecycle、model call 或 Tool call 周围执行 | `create_middleware(...)` 返回一个 `AgentMiddleware` |
| Agent Additional Prompt（AAP） | `abefore_agent` | 构造 current Agent 私有初始 `messages` |
| Command | Workflow Node invocation | 返回官方`Command(update, goto)`，并可启动独立Graph Run |
| Agent/Workflow Event Output | event projection | 把 event 投影为公开字符串 |

Command 和 Event Output 的代码 contract 见[编写 Python extension](06-python-extensions.md)。

## 3. 创建配置独占 package

先从当前实例读取 template catalog：

```text
GET /agent-shell/api/python-package-templates/custom-tool
GET /agent-shell/api/python-package-templates/middleware
```

选择 response 中存在的精确 `key + revision`，再创建 Component：

```http
POST /agent-shell/api/blocks/custom-tool
```

```json
{
  "name": "Workflow label tool",
  "python_package": {
    "folder": ""
  },
  "python_package_template": {
    "key": "<catalog key>",
    "revision": "<catalog revision>"
  }
}
```

Custom Middleware 使用相同 payload shape，endpoint 为：

```http
POST /agent-shell/api/blocks/custom-middleware
```

创建成功后保存 Component UUID，并读取 private package：

```text
GET /agent-shell/api/blocks/custom-tool/<tool UUID>/python-package
GET /agent-shell/api/blocks/custom-middleware/<middleware UUID>/python-package
```

response 给出 owner folder、manifest、文件列表、revision 与 dependency status。通过 File Manager API 或用户授权的本地编辑器修改该 package 中的 `main.py`、local module 和 `requirements.txt`。

## 4. Custom Tool

Custom Tool package 的 module-level entry 是同步无参 `create_tool()`。它返回一个 LangChain `BaseTool`。

```python
from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool


@tool
def agent_label(text: str, runtime: ToolRuntime) -> str:
    """Attach the configured Main Agent identity to a text label."""

    return f"{runtime.context.main_agent_id}:{text.strip()}"


def create_tool() -> BaseTool:
    return agent_label
```

模型看到的 Tool contract 来自：

- Tool name：默认使用 function name，也可以通过 `@tool("name")` 指定；
- description：来自 docstring 或显式 description；
- input schema：来自 typed parameter；
- result：由 Tool callable 返回给 Agent loop。

`ToolRuntime` 是 LangChain 注入参数，不进入发送给模型的 Tool input schema。它提供：

- `runtime.state`：current Agent State；
- `runtime.context`：current runtime context，包含明确命名的Lifecycle、root Graph、Run和Agent profile identity；
- `runtime.execution_info`：LangGraph 提供的 current thread、run、checkpoint、task 和 node attempt 信息；
- `runtime.store`：Server注入的LangGraph Store；
- `runtime.stream_writer`：Tool stream writer；

Tool 的参数名 `runtime` 与 `config` 由 LangChain 保留。Runtime access 写在 Tool callable 中；`create_tool()` 在 assembly construction stage 执行，没有某次 invocation 的 Runtime。

## 5. 装配 Custom Tool

Main Agent 使用：

```json
{
  "tool_refs": [
    {
      "tool_id": "<custom tool UUID>"
    }
  ]
}
```

Subagent 在 `settings` 中保存自己的列表：

```json
{
  "settings": {
    "tool_refs": [
      {
        "tool_id": "<custom tool UUID>"
      }
    ]
  }
}
```

修改已有 Agent 时先读取完整对象，再把 reference 合入 endpoint 的完整可写 payload：

```text
GET /agent-shell/api/main-agents/<main Agent UUID>
PUT /agent-shell/api/main-agents/<main Agent UUID>

GET /agent-shell/api/subagents/<Subagent UUID>
PUT /agent-shell/api/subagents/<Subagent UUID>
```

每个列表内的 UUID 必须唯一。Custom Tool、Filesystem Tool、Middleware 提供的 Tool、同步Subagent的`task`和AsyncSubAgent的五个task工具共享模型可见Tool namespace；重复Tool name会在Agent assembly validation中返回错误。

## 6. Custom Middleware factory

Custom Middleware package 的 module-level entry 是同步 `create_middleware(...)` factory，并返回一个官方 LangChain `AgentMiddleware`。

factory 可以按参数名声明当前装配需要的数据。Agent Shell 当前可以提供：

- `agent` / `owner` identity；
- `package`、`package_id` 和当前 `block`；
- `assembly`、`config` / `blocks` 与 `references`；
- `backend`、`model` 和 `tools`；
- `scope`、`workflow_node_id` 与 `request_id`。

factory 也可以用 `**kwargs` 接收其余可用值。没有 default 的参数必须存在于当前 construction context；缺失时 assembly 失败。每次 invocation 的 State、Runtime Context 和 Store 在 Middleware hook 中读取。

下面的Middleware在Agent invocation开始时把配置identity写入自己的private Agent State channel：

```python
from typing import Annotated, Any
from typing_extensions import NotRequired, TypedDict

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import PrivateStateAttr
from langgraph.runtime import Runtime


class InvocationIdentityState(TypedDict):
    configured_agent: NotRequired[
        Annotated[dict[str, str], PrivateStateAttr]
    ]


class InvocationIdentityMiddleware(AgentMiddleware):
    state_schema = InvocationIdentityState

    def __init__(self, *, agent: dict[str, Any], package_id: str) -> None:
        super().__init__()
        self._agent_id = agent["id"]
        self._agent_type = agent["type"]
        self._name = f"InvocationIdentityMiddleware_{package_id}"

    @property
    def name(self) -> str:
        return self._name

    async def abefore_agent(
        self,
        state: dict[str, Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any]:
        del runtime
        return {
            "configured_agent": {
                "id": self._agent_id,
                "type": self._agent_type,
            }
        }


def create_middleware(
    agent: dict[str, Any],
    package_id: str,
    **_available: Any,
) -> AgentMiddleware:
    return InvocationIdentityMiddleware(agent=agent, package_id=package_id)
```

`PrivateStateAttr`使该字段属于Agent自己的State schema，并从模型可见State中隐藏。Workflow的`shared_vars`属于另一个root Graph，Agent Middleware不写入该channel。多个Middleware需要同名State key时，应由一个明确owner定义reducer或使用各自唯一key。

## 7. Middleware hook

LangChain `AgentMiddleware` 提供 node-style hook 与 wrap-style hook：

| 同步 hook | Agent Shell async hook | 执行时点 |
| --- | --- | --- |
| `before_agent` | `abefore_agent` | 每次 Agent invocation 开始前一次 |
| `before_model` | `abefore_model` | 每次 model call 前 |
| `after_model` | `aafter_model` | 每次 model response 后 |
| `after_agent` | `aafter_agent` | 每次 Agent invocation 完成后一次 |
| `wrap_model_call` | `awrap_model_call` | 包围每次 model call |
| `wrap_tool_call` | `awrap_tool_call` | 包围每次 Tool call |

一次包含 Tool call 的 Agent invocation 会经过以下 hook 边界：

```text
abefore_agent
  -> abefore_model
  -> awrap_model_call -> model
  -> aafter_model
  -> awrap_tool_call -> Tool
  -> 下一轮 model-tool loop
aafter_agent
```

node-style hook 读取 `state` 与 `runtime`，并通过返回 dict 提交 Agent State update。wrap-style hook 接收 request 与 handler，可以在 handler 前后执行代码、修改 request、处理 result、short-circuit 或 retry；返回形状使用当前 LangChain public contract。

Agent Shell 通过 async Agent execution path 运行 Middleware。自定义类覆盖任一同步 hook 时，同时实现对应 async hook；缺少 async counterpart 会以 `middleware_package_async_hook_required` 拒绝 assembly。只实现 async hook 的 Middleware 直接定义表中的 async method。

一个 Middleware class 可以实现多个 hook。它们属于同一个实例，并在 `middleware_refs` 中共享同一排序位置。

## 8. Middleware 顺序

Main Agent 使用：

```json
{
  "middleware_refs": [
    {
      "middleware_id": "<middleware UUID A>"
    },
    {
      "middleware_id": "<middleware UUID B>"
    }
  ]
}
```

Subagent 把相同形状保存在 `settings.middleware_refs`。LangChain 按以下顺序组合列表：

- `before_*`：从第一项到最后一项；
- `after_*`：从最后一项到第一项；
- `wrap_*`：按列表嵌套，第一项位于最外层。

多个 Middleware 修改同一个 State channel 或 model request 时，后续 hook 看到前序 hook 已提交的结果。保存 `middleware_refs` 前应明确这些更新的组合结果。

## 9. Agent Additional Prompt

Agent Additional Prompt是内置Custom Middleware template。它在`abefore_agent`中读取current Agent可访问的request或delegated messages，以及显式选择的Store artifact与Filesystem，然后返回该Agent私有的初始`messages`和checkpointed initialization marker。

创建入口：

```text
GET /agent-shell/api/python-package-templates/middleware
key == "内置示例-agent-additional-prompt"
```

AAP首次运行时使用`Overwrite(convert_to_messages(...))`设置Thread初始`messages`；同一stateful Thread后续Run看到private marker后不再附加。材料选择、Main Agent与Subagent的输入差异见[Agent Additional Prompt](../agent-additional-prompt.md)。

## 10. Package 与 dependency

- private package 的 folder 等于 Component 配置名称，`package.json.id` 等于 Component UUID；
- `package.json` 的 family 和 adapter 与 Custom Tool 或 Custom Middleware 类型一致；
- local module 使用 relative import，例如 `from .helpers import build_value`；
- Python 3.12 standard library、平台公开的 LangChain、LangGraph、Deep Agents 和 `agent_shell` helper 使用当前锁定版本；
- package 直接 import 的其他 third-party package 声明在自己的 `requirements.txt`；
- requirements 变化后重启 Agent Shell，并再次读取 `dependency_status`；
- source 变化在下一次 request materialization 时加载；
- Python extension 以 Agent Shell service process 权限执行，属于 trusted code。

通用目录、manifest、File Manager revision、dependency status 与导入规则见[编写 Python extension](06-python-extensions.md)。

## 11. 验证路径

```text
读取 template catalog
  -> 创建 Custom Tool 或 Custom Middleware
  -> 回读 private package
  -> 编辑 source 和 requirements
  -> 装配到目标 Agent 的 ordered refs
  -> GET 回读 Agent configuration
  -> Repository validation
  -> Graph validation 与 publish
  -> dependency_status == ready
  -> 真实 invocation 覆盖目标 Tool 或 hook
```

常见失败 owner：

- `create_tool()` 缺失、带参数、是 async function 或返回值不是 `BaseTool`；
- `create_middleware(...)` 缺失、是 async function、请求 unavailable construction argument 或返回值不是 `AgentMiddleware`；
- 同步 hook 缺少对应 async hook；
- Tool name 与当前 Agent 的其他模型可见 Tool 重复；
- `tool_refs` 或 `middleware_refs` 引用不存在、重复或不属于 current Repository 的 UUID；
- package manifest 与 owner UUID 不一致；
- dependency status 是 `restart_required` 或 `failed`；
- Tool、Middleware 或 Provider 的 runtime path 在真实 invocation 中失败。

LangChain public API 参考 [Tools](https://docs.langchain.com/oss/python/langchain/tools)、[Custom middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom) 和 [Runtime](https://docs.langchain.com/oss/python/langchain/runtime)。当前 Agent Shell 接入能力仍以实例 Catalog、项目源码 contract 与锁定版本为准。

下一步阅读[构建 Workflow Graph](05-build-workflow-graph.md)。
