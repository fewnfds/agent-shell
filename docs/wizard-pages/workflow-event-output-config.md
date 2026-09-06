# Workflow Event Output

Workflow Event Output 是可复用 Workflow 组件。`main.py` 的协议入口是同步 `output(event, origin)`：`event` 为 LangGraph v3 原始 `ProtocolEvent`，`origin` 为 Agent Shell Workflow root Graph Run 身份。它只负责把 Workflow-owned event 投影为文本；返回空字符串表示过滤。流式 text/reasoning 需要可中断的展示边界时，可以提供可选同步 `segment_end(event, origin)`。

```python
def output(event, origin):
    method = event.get("method")
    if method != "custom":
        return ""
    params = event.get("params", {})
    data = params.get("data") if isinstance(params, dict) else None
    return f"Workflow progress: {data}\n"


def segment_end(event, origin):
    return ""


def run_output(event, origin):
    if event.get("type") == "agent_shell.workflow_run":
        return f"Workflow {event.get('status', '')}\n"
    return ""
```

`event` 保持官方 envelope：`seq` 严格递增，`method` 是 channel，`params.namespace` 是从 root 到 nested graph 的 segment 路径，`params.timestamp` 是 wall-clock timestamp，`params.data` 是 channel-specific Python payload。不得期待 `event_type`、`phase`、`message` 或 canvas Node identity 等平台重新封装字段；Graph 内部细节直接从原始 event 读取。

`origin` 字段为 `lifecycle_id`、`graph_kind=workflow`、`run_id`、`thread_id`、`assistant_id`、`caller_run_id`、`operation_id`、`workflow_id`，以及为空的 Agent profile 字段。它保存官方执行对象引用和 Shell root Graph身份；model run、Tool、namespace、seq 和 payload 细节继续从 `event` 读取。

`output`、可选 `segment_end` 和可选 `run_output` 的函数签名都必须恰好接受 `event, origin`，不接受异步函数、默认参数或额外参数。异常或非字符串返回值以 `event_output.execution_failed`（502）终止运行；依赖未准备好时返回 `python_package.dependencies_not_ready`（409）。原始事件不会因过滤而丢失，Response Stream Scheduler 仅负责所有 Run 之间的先后、公平排队和节流。

当前公开运行流可到达 `messages`、`tools`、`lifecycle`、`values` 和 `custom` method。只有 message text 和 reasoning block 使用流式 presentation segment；其他 raw event 与 Shell Workflow Run event 都以一次性完整文本排队。Runtime 只在 text/reasoning `content-block-start` 上调用 `segment_end`，并把返回值作为不透明、可选的 segment 尾文本保存。正常 `content-block-finish` 的 `output` 返回值可以覆盖它；没有定义 end 或返回空字符串时，Scheduler 在 idle、terminal 等边界只释放 writer，不生成闭合文本。Scheduler 不硬编码 `</details>`，也不要求 start/end 是 HTML 或成对标签。

Tool call declaration、result/error 和 started/progress 若被投影为非空文本，均按各自原始事件到达顺序形成 atomic frame。Scheduler 不配对或解释 Tool transaction。

Shell Run 开始、完成、失败状态不是官方 ProtocolEvent。需要显示这些产品状态时，在同一个 package 中提供可选同步 `run_output(run_event, origin)`；它接收 `type="agent_shell.workflow_run"` 的小型产品事件。不要把该状态写回 `event`。

Workflow通过`workflow_event_output_id`绑定零或一个组件。可达channel的原始Python payload可直接读取；是否进入history、checkpoint或debug journal由各自观测边界决定。Workflow Run只使用本组件；Main Agent Run使用其自身Agent Event Output。

内置 `all-events` 示例将每个当前事件和 Workflow Run start/end/error 分派给独立函数，以默认展开的 `<details open>` 显示正文，并在独立的低对比度小号灰字行中显示 `key=value | key=value` metadata。它只对 assistant text 和 reasoning 使用 start/delta/finish 流式输出。

`all-events` 会公开它收到的完整 State、message、Tool 参数/结果、媒体引用、路径和运行身份。它只适合受信任的诊断环境；常规公开响应应复制必要分支并过滤其余事件。

从 `GET /agent-shell/api/python-package-templates/workflow-event-output` 取得模板 `key` 与 `revision`，提交到 `POST /agent-shell/api/blocks/workflow-event-output`。package folder 等于配置名称，manifest ID 等于配置 UUID。
