# Agent Event Output

Agent Event Output 是 Agent 配置拥有的 Python 扩展。`main.py` 必须提供同步入口 `output(event, origin)`；`event` 是 LangGraph v3 原始 `ProtocolEvent` envelope，`origin` 是 Agent Shell 对当前 Run 和 Workflow Node 的显式身份。入口返回 `str`，空字符串过滤公开响应。需要为流式 text/reasoning 定义可中断的展示边界时，可以再提供可选同步入口 `segment_end(event, origin)`。

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


def segment_end(event, origin):
    # Runtime 只在 text/reasoning content-block-start 上调用该 hook。
    return ""
```

`event` 不经过 JSON round-trip，也不附加产品字段。按 `event["method"]` 读取 `params.namespace`、`params.timestamp` 和 `params.data`；`messages` 的 data 是 `(payload, metadata)`，其中 metadata 通常含 `run_id`、`langgraph_node` 和 provider metadata。`tools`、`custom`、`values`、`updates`、`tasks`、`input`、`input.requested`、`lifecycle` 等 channel 的 data 保持 LangGraph/LangChain Python 对象原样。

`origin` 只包含产品身份：

| key | 含义 |
| --- | --- |
| `lifecycle_id` | Agent Shell Lifecycle UUID |
| `run_id` | 当前官方 Workflow Run ID |
| `thread_id` | 当前官方 Thread ID |
| `assistant_id` | 当前官方 Assistant ID |
| `caller_run_id` | 调用当前 Run 的 Run ID；请求入口 Run 为空 |
| `operation_id` | caller 为本次跨 Workflow 调用指定的 operation ID；请求入口 Run 为空 |
| `workflow_id` | 当前 Workflow 配置 UUID |
| `workflow_node_id` | 当前 canvas Node ID |
| `node_invocation_id` | 当前 Node invocation ID |
| `agent_profile_id` | Main Agent 配置 UUID |
| `subagent_profile_id` | Subagent 配置 UUID（无则为空） |

model run、Tool call、`seq`、namespace 和 channel-specific 字段一律从官方 `event` 读取，不从 `origin` 重复推导。无法从 namespace 和冻结 Workflow registry 证明 Node/Agent 归属时，相关 origin 字段为空。

函数签名必须恰好是 `def output(event, origin)`；定义 `segment_end` 时，其签名也必须恰好是 `def segment_end(event, origin)`。两者都不接受 `async def`、默认参数、额外参数、`*args` 或 `**kwargs`。脚本异常或返回非字符串会以 `event_output.execution_failed`（502）终止本次运行；依赖未准备好时返回 `python_package.dependencies_not_ready`（409）。

## Streaming 与 Run lifecycle

每个原始 ProtocolEvent 调用一次 `output`。脚本依据官方 message payload 的 `content-block-start`、`content-block-delta` 和 `content-block-finish` 自行决定首文本、delta 和正常尾文本；不要依赖平台伪造的 start/end envelope，也不要修改模块全局状态。当前公开运行流可到达 `messages`、`tools`、`lifecycle`、`values` 和 `custom` method；未来 method 仍可由 fallback 分支作为完整事件显示。

只有 text 和 reasoning block 使用流式 presentation segment。Runtime 在对应 `content-block-start` 上额外调用一次可选 `segment_end(event, origin)`，保存它返回的不透明字符串：idle 切换、Run terminal 或 continuation 分段需要释放 writer 时才输出这个字符串。没有定义 hook 或返回空字符串时只释放 writer，不产生尾文本。正常 `content-block-finish` 的 `output` 返回非空字符串时使用该正常尾文本；返回空字符串时使用 start 时保存的 `segment_end`。Scheduler 不解析 HTML，也不假定 `<details>`、闭合标签或任何固定格式。

Tool call 在 `messages/content-block-finish` 形成完整 declaration；terminal result/error 来自完整 `tools` event。Scheduler 按 lane、model turn 和 Tool call ID 配对两段已经投影好的完整文本，使 declaration 与 outcome 作为不可插队项相邻发送。Tool started/progress 等其他事件各自作为完整事件排队，不参与 text/reasoning 流式 segment。

同一 model run 同时出现 streamed message events 与完整 `AIMessage` snapshot 时，runtime 仍调用两次 `output`，但完整 snapshot 的投影结果不会再次进入公开队列，避免重复正文。model run identity 直接读取 message metadata 的官方 `run_id`。

Shell 合成的 Workflow Run 状态不是 Agent-owned ProtocolEvent，由 Workflow Event Output 的可选 `run_output(run_event, origin)` 处理。Agent Event Output 提供 `output(event, origin)` 和可选 `segment_end(event, origin)`。

媒体、usage、官方 Run/State 观测和 Python payload 不由 Event Output 改写；返回空字符串只影响公开文本投影。Subagent 事件沿用所属 Main Agent package，`origin["subagent_profile_id"]` 用于区分来源。

内置 `all-events` 示例将每个当前事件交给独立函数，以默认展开的 `<details open>` 输出正式消息，并在末尾用小号灰字显示 `key=value | key=value` debug metadata。示例只让 assistant text 和 reasoning 流式输出；Tool call、Tool result、生命周期、State、custom 和其他事件都是完整块。

`all-events` 会公开它收到的完整 State、message、Tool 参数/结果、媒体引用、路径和运行身份。它只适合受信任的诊断环境；面向普通 API 使用方时，应从该示例复制所需分支并显式过滤其余事件。

## 配置保存

从 `GET /agent-shell/api/python-package-templates/agent-event-output` 取得模板 `key` 与 `revision`，提交到 `POST /agent-shell/api/blocks/agent-event-output`。首次保存后服务端生成配置 UUID，package folder 等于配置名称，manifest ID 等于配置 UUID。源码位于当前 Configuration Repository 的 `data/config_repos/<repository-name>/python_packages/agent_event_output/<configuration-name>/` 独占目录。
