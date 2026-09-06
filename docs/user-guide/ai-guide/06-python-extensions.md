# 编写 Python extension

Agent Shell支持五类配置独占Python extension：Custom Tool、Custom Middleware、Command、Agent Event Output和Workflow Event Output。完成结果是正确package、真实配置引用和一次最接近的行为验证。

## 1. 通用package

从对应template创建Component后，private package位于current Configuration Repository。每个package包含`package.json`和入口`main.py`，可选`requirements.txt`。

代码运行在Agent Shell服务进程的受信任边界内，没有sandbox。不要在代码中硬编码secret；通过既定Model/MCP binding或环境owner取得。

async Command与Middleware hook不得直接执行阻塞网络、数据库、文件或子进程I/O。优先原生async API；无法异步化时只在资源唯一owner处精确使用`asyncio.to_thread()`。

## 2. Command contract

```python
from langgraph.types import Command


def create_command():
    async def command(state, runtime):
        current = state.get("shared_vars", {})
        target = "done" if current.get("ready") else "retry"
        return Command(
            update={"shared_vars": {"last_target": target}},
            goto=target,
        )

    return command
```

要求：

- `create_command()`是同步无参factory；
- 返回callable固定为`async command(state, runtime)`；
- callable返回官方`langgraph.types.Command`；
- `update`只能包含`shared_vars`mapping；
- `goto`是current Command outgoing Edge声明的目标Node ID；
- 不使用`Send`、`resume`或跨graph routing；
- 不读取Canvas Edge ID、handle或layout。

需要独立AI工作时调用：

```python
handle = await runtime.context.agent_runs.start(
    "<main-agent-uuid>",
    [{"role": "user", "content": "Perform the review."}],
    operation_id="review:item-42",
)
result = (await runtime.context.agent_runs.join([handle.run_id]))[0]
```

child结果不会自动写入Workflow State。Command明确选择需要的projection并放入`Command.update`。

## 3. Custom Tool

```python
from langchain.tools import tool


@tool
async def lookup(query: str) -> str:
    """Look up one record."""
    ...


def create_tool():
    return lookup
```

`create_tool()`返回一个`BaseTool`。需要State、Context、Store或stream writer时使用LangChain官方`ToolRuntime`注入，不把runtime参数暴露给模型schema。

## 4. Custom Middleware

```python
from langchain.agents.middleware import AgentMiddleware


class CustomPolicy(AgentMiddleware):
    async def abefore_agent(self, state, runtime):
        return None


def create_middleware(agent):
    return CustomPolicy()
```

Main Agent和Subagent分别保存ordered Middleware refs。before hook正序，after hook逆序，wrap hook按列表嵌套。返回官方State update，不维护第二套agent loop。

AAP模板使用private checkpointed marker，只在stateful Agent Thread第一次运行时注入初始messages。

## 5. Event Output

Agent与Workflow Event Output都提供同步纯projection入口：

```python
def output(event, origin):
    if event.get("method") != "custom":
        return ""
    return str(event.get("params", {}).get("data", ""))
```

输入是原始LangGraph v3 ProtocolEvent和Shell origin；返回必须是字符串，空字符串隐藏event。projection不执行阻塞I/O，不修改State、checkpoint或routing。

Agent Event Output只用于Main Agent Run；Workflow Event Output只用于Workflow Run。不要在Workflow脚本中解析embedded Agent来源。

## 6. Dependency与验证

`requirements.txt`只声明该extension真实使用且与核心lock兼容的公开发行包。修改后重启Agent Shell，让启动器按可达配置指纹准备共享extension layer。

交付前：

- 读取Component validation；
- 确认package manifest owner UUID正确；
- 确认factory和返回对象符合对应contract；
- 对async路径检查阻塞I/O；
- 通过Main Agent或Workflow真实引用触发一次最接近的行为；
- 检查runtime diagnostics，而不是只证明模块可import。
