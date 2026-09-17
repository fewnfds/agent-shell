# 构建 Workflow Graph

本章用于创建和发布Start/Command/End control Graph。Main Agent不作为Canvas Node；需要AI时由Command启动独立Agent Run。

## 1. 准备引用

创建Graph前准备：

- Workflow UUID；
- 每个Command配置UUID；
- 可选的 External Agent 预设UUID；
- Command代码中使用的Main Agent/Workflow UUID；
- 可选Workflow Event Output UUID。

Main Agent目标不进入Graph document。它是Command package或其配置明确使用的运行依赖。

## 2. 创建Workflow metadata

```http
POST /agent-shell/api/workflows
Content-Type: application/json

{
  "name": "review-pipeline",
  "description": "Run deterministic preparation and an independent review agent.",
  "is_model_entry": true,
  "on_disconnect": "cancel"
}
```

新Workflow保持`enabled=false`，直到Graph正式保存通过。

## 3. Graph document

```json
{
  "definition": {
    "schema_version": 1,
    "state_contract": "agent-shell.workflow.control.v1",
    "schema_source": "from pydantic import BaseModel, ConfigDict\n\nclass State(BaseModel):\n    model_config = ConfigDict(extra=\"forbid\")\n    selected_target: str\n",
    "nodes": [
      {"id": "start", "type": "start", "type_version": 1, "config": {}},
      {
        "id": "review",
        "type": "command",
        "type_version": 1,
        "config": {
          "command_id": "<command-uuid>",
          "external_agent_id": "<external-agent-uuid>"
        }
      },
      {"id": "end", "type": "end", "type_version": 1, "config": {}}
    ],
    "edges": [
      {
        "id": "start-review",
        "source": "start",
        "source_handle": "next",
        "target": "review",
        "target_handle": "in"
      },
      {
        "id": "review-end",
        "source": "review",
        "source_handle": "next",
        "target": "end",
        "target_handle": "in"
      }
    ]
  },
  "layout": {
    "nodes": {
      "start": {"x": 80, "y": 160},
      "review": {"x": 320, "y": 160},
      "end": {"x": 560, "y": 160}
    },
    "viewport": {"x": 0, "y": 0, "zoom": 1}
  }
}
```

layout只供Vue Flow编辑；runtime不读取position或viewport。

`schema_source`可省略或为`null`。省略时不校验Workflow State的键名与类型；声明时内容必须是合法Python，并至少定义Pydantic`State`。入口输入与每个Command的update结果都必须满足该模型。未知字段是否允许由模型的`model_config`决定。

## 4. Node规则

- 恰有一个Start和一个End；
- Start/End ID固定且不可删除；
- Command ID在Graph内唯一，可编辑；
- Node type/version必须存在于后端Catalog；
- Command config保存`command_id`，并可保存一个可选的`external_agent_id`；
- 所有可执行Command从Start可达；
- End可以没有incoming Edge；
- reachable leaf Command可自然结束。

## 5. Edge规则

Edge只有`id/source/source_handle/target/target_handle`五个字段。

- Start和Command的output handle是`next`；
- Command和End的input handle是`in`；
- 不允许self-loop；
- 同一个有向`source -> target` pair只能有一条Edge；
- endpoint可有多个合法连接；
- Command outgoing Edge声明脚本可goto的target Node ID；
- Start outgoing Edge编译为static activation。

条件、loop和fan-out都由Command返回一个或多个target Node ID表达。Edge不保存branch key、dispatch key或payload。

## 6. 保存draft与publish

保存不完整工作：

```http
PUT /agent-shell/api/workflows/<workflow-id>/draft
```

draft执行wire解析并原子设置`enabled=false`。

正式校验：

```http
POST /agent-shell/api/workflows/<workflow-id>/validate
```

正式保存：

```http
PUT /agent-shell/api/workflows/<workflow-id>/graph
```

后端重复执行完整校验，确认Catalog、topology、Command引用、package和compile全部成立后原子设置`enabled=true`。不能通过metadata PUT绕过publish。

## 7. 运行前检查

- state contract精确为`agent-shell.workflow.control.v1`；
- 每个Command返回官方`Command`；
- 每个可能goto目标都有同源outgoing Edge；
- Command只依赖官方`Command(update, goto)`与显式Run facade；
- child Run使用稳定operation ID；
- loop有业务退出条件；
- Workflow Event Output只投影Workflow自己的event。

## 8. MCP Tool

MCP Tool 与 Workflow 是并列资源，API 路径为：

```text
POST   /agent-shell/api/mcp-tools
GET    /agent-shell/api/mcp-tools/<mcp-tool-id>
PUT    /agent-shell/api/mcp-tools/<mcp-tool-id>/draft
POST   /agent-shell/api/mcp-tools/<mcp-tool-id>/validate
PUT    /agent-shell/api/mcp-tools/<mcp-tool-id>/graph
DELETE /agent-shell/api/mcp-tools/<mcp-tool-id>
```

创建 metadata 时名称必须是唯一的合法 MCP tool name：

```text
^[A-Za-z0-9._-]{1,128}$
```

Graph document 的 `definition.schema_source` 为可选 Python 源码。MCP Tool 声明 schema 时必须定义 Pydantic `State`、`Input` 和 `Output`；每个 `Input` 字段必须存在于 `State`，每个 `Output` 字段也必须存在于 `State`。没有 schema 时使用开放 mapping State。Command 输入仍是扁平 state，不使用 `messages[]`、`input` 或 `initial_state` 包装。

MCP Tool 不接受 External Agent；正式保存会拒绝任何依赖 Lifecycle 或外部会话的 Command。`/agent-shell/api/mcp-tools/<id>/graph` 只在完整校验通过后设置 `enabled=true` 并刷新官方 Assistant。保存 draft 会把 `enabled` 设为 `false`，并先从 `/mcp tools/list` 隐藏；draft 被 validation 拒绝（422）时不改变已发布状态。已发布 MCP Tool 依赖的 Command 被删除时，该工具自动取消发布并从 `/mcp` 消失；服务启动时按当前 Configuration Repository 的记录重新对齐官方 Assistant。

验收时使用带管理凭据的官方 `/mcp` JSON-RPC：

1. `initialize`；
2. `tools/list`，确认 name、description 和 Pydantic 自动生成的 `inputSchema`；
3. `tools/call`，确认 arguments 直接进入 Graph State，结果是最终 Graph value；不要期望 Workflow Event Output；
4. 连续调用两次，确认第二次没有继承第一次 State；
5. 保存 draft 或删除后，确认该 tool 不再出现在 `tools/list`。
