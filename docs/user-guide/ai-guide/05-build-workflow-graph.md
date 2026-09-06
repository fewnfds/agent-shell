# 构建 Workflow Graph

本章用于创建和发布Start/Command/End control Graph。Main Agent不作为Canvas Node；需要AI时由Command启动独立Agent Run。

## 1. 准备引用

创建Graph前准备：

- Workflow UUID；
- 每个Command配置UUID；
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
  "durability": "async",
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
    "nodes": [
      {"id": "start", "type": "start", "type_version": 1, "config": {}},
      {
        "id": "review",
        "type": "command",
        "type_version": 1,
        "config": {"command_id": "<command-uuid>"}
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

## 4. Node规则

- 恰有一个Start和一个End；
- Start/End ID固定且不可删除；
- Command ID在Graph内唯一，可编辑；
- Node type/version必须存在于后端Catalog；
- Command config只保存`command_id`；
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
