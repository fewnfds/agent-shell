# Python Schema

Python Schema 是可复用工作流组件，把 Workflow 与 MCP Tool 的 State 结构保存为一份独立、可被多个配置引用的 Python 源码。它属于当前 active Configuration Repository，字段只有 `name` 与 `source`。

```python
from pydantic import BaseModel, ConfigDict


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_target: str
```

保存时后端加载源码并要求它至少定义 Pydantic `State` 模型；源码不能为空。组件合法性、`Input`/`Output` 字段约束和运行时 State 校验全部由后端判定，前端只编辑这一段源码。

## 引用方式

Workflow 与 MCP Tool 的 metadata 都保存可选 `python_schema_id`，在同一张 Python Schema Card 中选择组件，不引用时留空。

| 引用方 | 源码要求 | 运行效果 |
| --- | --- | --- |
| Workflow | 至少定义 `State` | Run 入口输入与每个 Command 的 `update` 结果都按 `State` 校验 |
| MCP Tool | 定义 `State`、`Input` 和 `Output` | `Input` 生成官方 `inputSchema`，`Output` 投影 `State` 的同名字段 |

MCP Tool 的每个 `Input` 字段必须存在于 `State`，每个 `Output` 字段也必须存在于 `State`。LangGraph 直接使用这三个模型，并把 Pydantic 生成的 JSON Schema 作为官方 `inputSchema`。未引用 Python Schema 时使用开放 mapping State，参数直接成为扁平键，不做键名与类型校验。

Graph document 不保存 Python 源码。Python Schema 组件的源码只属于组件本身，Workflow 与 MCP Tool 只保存它的 UUID。

## 校验与生命周期

- 引用目标不存在或不是 Python Schema 组件时，Workflow/MCP Tool 发布校验返回 `configuration.reference_not_found` 或 `configuration.reference_type_mismatch`；
- 源码无法加载、没有 `State`（Workflow）或缺少 `Input`/`Output`（MCP Tool）时返回 `workflow.schema_invalid` 或对应 MCP Tool 契约错误；
- Run 入口输入不符合 `State` 时以 `workflow.state_invalid` 在进入 Run 前失败；Command 的 `update` 结果不符合时让该 Run 以同一错误码结束（脚本自身异常仍是 `workflow.command_failed`）；
- 未声明时不做决定论式的键名与类型校验；模型对未知字段的处理遵循 Pydantic 配置，例如 `ConfigDict(extra="forbid")` 会拒绝未声明键；
- 删除被引用的 Python Schema 时，引用方 UUID 原样保留，依赖的 Workflow/MCP Tool 自动降级为未发布，Repository 校验产生 `configuration.reference_not_found`；
- Lifecycle snapshot、Workflow runtime 和 MCP Tool runtime 都从冻结的组件记录解析源码，不读取 live 配置。

Workflow 与 MCP Tool 的完整 Graph 契约见 [Workflow 配置](../user-guide/configuration-workflow.md) 和 [MCP 连接、映射与调用](../user-guide/mcp.md)。
