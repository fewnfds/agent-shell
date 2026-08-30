# Workflow Event Output

Workflow Event Output 是可复用 Workflow 组件。`main.py` 的协议入口是同步 `output(event, origin)`：`event` 为 LangGraph v3 原始 `ProtocolEvent`，`origin` 为 Agent Shell Run、Workflow 和 Node 身份。它只负责把 Workflow-owned event 投影为文本；返回空字符串表示过滤。

```python
def output(event, origin):
    method = event.get("method")
    if method != "custom":
        return ""
    params = event.get("params", {})
    data = params.get("data") if isinstance(params, dict) else None
    return f"Workflow progress: {data}\n"


def run_output(event, origin):
    if event.get("type") == "agent_shell.workflow_run":
        return f"Workflow {event.get('status', '')}\n"
    return ""
```

`event` 保持官方 envelope：`seq` 严格递增，`method` 是 channel，`params.namespace` 是从 root 到 nested graph 的 segment 路径，`params.timestamp` 是 wall-clock timestamp，`params.data` 是 channel-specific Python payload。不得期待 `event_type`、`phase`、`message`、`workflow_node_id` 等平台重新封装字段；Node 和 Agent 身份从 `origin` 获取。

`origin` 字段为 `lifecycle_id`、`workflow_run_id`、`parent_workflow_run_id`、`workflow_id`、`workflow_role`、`background_task_id`、`run_depth`、`workflow_node_id`、`node_invocation_id`、`agent_profile_id` 和 `subagent_profile_id`。它只保存 Shell 产品身份；model run、Tool、namespace、seq 和 payload 细节继续从 `event` 读取。无法证明归属时不猜测身份。

函数签名必须恰好是 `def output(event, origin)`，不接受异步函数、默认参数或额外参数。异常或非字符串返回值以 `event_output.execution_failed`（502）终止运行；依赖未准备好时返回 `python_package.dependencies_not_ready`（409）。原始事件不会因过滤而丢失，Response Stream Scheduler 仅负责所有 Run 之间的先后、公平排队和节流。

Shell Run 开始、完成、失败状态不是官方 ProtocolEvent。需要显示这些产品状态时，在同一个 package 中提供可选同步 `run_output(run_event, origin)`；它接收 `type="agent_shell.workflow_run"` 的小型产品事件。不要把该状态写回 `event`。

Workflow 通过 `workflow_event_output_id` 绑定零或一个组件。`custom`、`values`、`updates`、`tasks`、`checkpoints`、`input`、`input.requested`、`debug` 等 channel 的原始 Python payload 可直接读取；是否进入历史、checkpoint 或 debug journal 由各自观测边界决定。canvas Agent Node 的 ProtocolEvent 由 Agent Event Output 处理，Workflow-owned non-Agent event 由本组件处理。

从 `GET /api/python-package-templates/workflow-event-output` 取得模板 `key` 与 `revision`，提交到 `POST /api/blocks/workflow-event-output`。package folder 等于配置名称，manifest ID 等于配置 UUID。
