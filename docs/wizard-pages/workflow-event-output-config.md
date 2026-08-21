# Workflow 事件输出

Workflow 事件输出是可复用的 Workflow 组件。每个 Workflow 可绑定零或一个；不绑定时，Workflow-owned 的非 Agent 事件不会写入
OpenAI 响应。画布 Agent Node 产生的事件仍使用各 Main Agent 的[Agent 事件输出](agent-event-output-config.md)。

它与 Agent 事件输出使用同一文件化扩展模式：一份配置独占一个 Python package，`main.py` 只提供一个同步
`output(event)`。所有 Workflow 事件在同一函数内按 `event["event_type"]` 分支；函数必须返回 `str`，空字符串表示过滤。
可从 `GET /api/python-package-templates/workflow-event-output` 加载内置示例，保存后源码与示例解耦。

内置示例使用与 Agent 事件输出相同的 HTML `details` 结构，并为 `custom`、`lifecycle`、`values`、`updates`、`tasks`、
`checkpoints`、`input`、`input.requested`、`debug` 和 `other` 分别保留分支。各分支都在同一个 `output(event)` 中按需处理；
未返回字符串的事件不会写入公开响应，Workflow runtime 仍保留完整事件分类供运行历史和调试使用。

```python
def output(event):
    if event["event_type"] != "values":
        return ""
    return (
        '<details type="workflow"><summary>*Workflow values*</summary>'
        f'{event["message"]}</details>\n'
    )
```

## 公共字段

所有 Workflow 事件都含有 Agent 事件输出文档列出的公共字段：`event_type`、`phase`、`sequence`、`timestamp`、
`namespace`、`agent_name`、`node`、`message`、`data`、`source_type`、`workflow_node_id`、`agent_profile_id`、
`subagent_profile_id`。这里的 `event_type` 是下表的 Workflow v3 method 分类，而不是统一写成 `custom`。

## 各 Workflow 事件 dict

| `event_type` | 附加 key | `data` 的 Python 值 |
| --- | --- | --- |
| `custom` | `channel`, `data_json` | `get_stream_writer()` 或 v3 custom event 写出的原始 Python payload |
| `lifecycle` | `status`, `finish_reason`, `error_code` | Workflow/script lifecycle envelope `dict` |
| `values` | `channel`, `data_json` | LangGraph `values` 模式的完整 Workflow State，通常为 `dict` |
| `updates` | `channel`, `data_json` | LangGraph `updates` 模式的 node-to-update `dict`，值可能继续包含消息或 `Command` 等 Python 对象 |
| `tasks` | `channel`, `data_json` | LangGraph task 事件的 Python payload，通常为 task 描述 `dict` 或集合 |
| `checkpoints` | `channel`, `data_json` | checkpoint 事件的 Python payload，通常为 `dict` |
| `input` | `channel`, `data_json` | 图输入事件的 Python payload，通常为输入 State `dict` |
| `input.requested` | `channel`, `data_json` | 请求外部输入/中断相关的 Python payload |
| `debug` | `channel`, `data_json` | LangGraph debug payload，通常为 `dict` |
| `other` | `channel`, `data_json` | 当前未归入上述 method 的原始 payload；`channel` 保留原 method 名 |

`channel` 对已知 State 类事件等于事件 method；`data_json` 是用于显示和简单拼接的 JSON 文本。要访问完整 State、消息
对象、`Command` 或其他 Python 值，应使用 `event["data"]`。这些对象来自锁定 LangChain/LangGraph 版本的 v3 语义 payload，
不保证本身 JSON-compatible；本页外层 `event` dict 和字段名才是 Agent Shell 的稳定输出脚本 contract。

脚本异常、返回非字符串、签名、依赖和独占目录边界与[Agent 事件输出](agent-event-output-config.md)相同。组件源码在受信任
服务进程中执行，不是 sandbox。创建 payload 结构也相同，仅 endpoint 改为 `POST /api/blocks/workflow-event-output`。
