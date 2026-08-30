# Agent Event Output

Agent Event Output 是 Agent 配置拥有的 Python 扩展。`main.py` 必须提供同步入口 `output(event, origin)`；`event` 是 LangGraph v3 原始 `ProtocolEvent` envelope，`origin` 是 Agent Shell 对当前 Run 和 Workflow Node 的显式身份。入口返回 `str`，空字符串过滤公开响应。

```python
def output(event, origin):
    if event.get("method") != "messages":
        return ""
    params = event.get("params", {})
    data = params.get("data") if isinstance(params, dict) else None
    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return ""
    payload = data[0]
    if not isinstance(payload, dict):
        return ""
    if payload.get("event") != "content-block-delta":
        return ""
    delta = payload.get("delta")
    return str(delta.get("text", "")) if isinstance(delta, dict) else ""
```

`event` 不经过 JSON round-trip，也不附加产品字段。按 `event["method"]` 读取 `params.namespace`、`params.timestamp` 和 `params.data`；`messages` 的 data 是 `(payload, metadata)`，其中 metadata 通常含 `run_id`、`langgraph_node` 和 provider metadata。`tools`、`custom`、`values`、`updates`、`tasks`、`input`、`input.requested`、`lifecycle` 等 channel 的 data 保持 LangGraph/LangChain Python 对象原样。

`origin` 只包含产品身份：

| key | 含义 |
| --- | --- |
| `lifecycle_id` | Agent Shell Lifecycle UUID |
| `workflow_run_id` | 当前 Workflow Run UUID |
| `parent_workflow_run_id` | 启动当前 Run 的父 Run；根 Run 为空 |
| `workflow_id` | 当前 Workflow 配置 UUID |
| `workflow_role` | `parent` 或 `child` |
| `background_task_id` | 当前后台任务 ID（无则为空） |
| `run_depth` | Workflow Run 深度 |
| `workflow_node_id` | 当前 canvas Node ID |
| `node_invocation_id` | 当前 Node invocation ID |
| `agent_profile_id` | Main Agent 配置 UUID |
| `subagent_profile_id` | Subagent 配置 UUID（无则为空） |

model run、Tool call、`seq`、namespace 和 channel-specific 字段一律从官方 `event` 读取，不从 `origin` 重复推导。无法从 namespace 和冻结 Workflow registry 证明 Node/Agent 归属时，相关 origin 字段为空。

函数签名必须恰好是 `def output(event, origin)`：不接受 `async def`、默认参数、额外参数、`*args` 或 `**kwargs`。脚本异常或返回非字符串会以 `event_output.execution_failed`（502）终止本次运行；依赖未准备好时返回 `python_package.dependencies_not_ready`（409）。

## Streaming 与 Run lifecycle

每个原始 ProtocolEvent 调用一次 `output`。脚本依据官方 message payload 的 `content-block-start`、`content-block-delta` 和 `content-block-finish` 自行决定首文本、delta 和尾文本；不要依赖平台伪造的 start/end envelope，也不要修改模块全局状态。工具声明和 outcome 分别按原始 `tools` event 调用，Response Stream Scheduler 负责事务配对和公平排队。

Shell 合成的 Run 状态不是 LangGraph ProtocolEvent。需要输出 Run 开始、完成或失败状态时，可在同一 package 中额外提供同步 `run_output(run_event, origin)`；该 hook 接收 `{"type": "agent_shell.workflow_run", "phase": ..., "status": ...}`，只处理产品状态，不替代 `output`。

媒体、usage、debug capture 和 Python payload 不由 Event Output 改写；返回空字符串只影响公开文本投影。Subagent 事件沿用所属 Main Agent package，`origin["subagent_profile_id"]` 用于区分来源。

## 配置保存

从 `GET /api/python-package-templates/agent-event-output` 取得模板 `key` 与 `revision`，提交到 `POST /api/blocks/agent-event-output`。首次保存后服务端生成配置 UUID，package folder 等于配置名称，manifest ID 等于配置 UUID。源码位于当前 Configuration Repository 的 `data/config_repos/<repository-name>/python_packages/agent_event_output/<configuration-name>/` 独占目录。
