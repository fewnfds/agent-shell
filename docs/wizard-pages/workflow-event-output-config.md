# Workflow 事件输出

Workflow 事件输出是可复用的 Workflow 组件，不属于 Agent capability。每个 Workflow 通过 `workflow_event_output_id` 可绑定零或一个；不绑定时，Workflow-owned 的非 Agent 事件不会写入 OpenAI 响应。画布 Agent Node 产生的事件仍使用各 Main Agent 的[Agent 事件输出](agent-event-output-config.md)。

它与 Agent 事件输出使用同一文件化扩展模式：一份配置独占一个 Python package，`main.py` 必须只提供恰好一个同步单参 `def output(event)`，不接受 `async def`、默认参数、额外参数、`*args` 或 `**kwargs`。所有 Workflow 事件在同一函数内按 `event["event_type"]` 分支；函数必须返回 `str`，空字符串表示过滤。
可从 `GET /api/python-package-templates/workflow-event-output` 加载内置示例，保存后源码与示例解耦。

内置示例使用与 Agent 事件输出相同的 HTML `details` 结构，并为 `custom`、`lifecycle`、`values`、`updates`、`tasks`、
`checkpoints`、`input`、`input.requested`、`debug` 和 `other` 分别保留分支。各分支都在同一个 `output(event)` 中按需处理；
返回空字符串只过滤 OpenAI 响应投影，不改变已经产生的 LangGraph v3 event；该 event 是否出现在运行历史或 checkpoint 取决于独立观测与持久化边界。

下面是只投影 `values` 的最小示例；完整 10 分支源码位于 `examples/workflow-components/workflow-event-output/default/main.py`：

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
`subagent_profile_id`。`event_type` 使用下表中的 Workflow v3 method 分类。

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

`channel` 对已知 State 类事件等于事件 method；`data_json` 是用于显示和简单拼接的 JSON 文本。要访问完整 State、消息对象、`Command` 或其他 Python 值，应使用 `event["data"]`。这些对象来自锁定 LangChain/LangGraph 版本的 v3 语义 payload，
不保证本身 JSON-compatible；本页外层 `event` dict 和字段名才是 Agent Shell 的稳定输出脚本 contract。

`output(event)` 抛异常或返回非字符串时以 `event_output.execution_failed`（502）终止本次运行；声明了尚未就绪的依赖时，请求期返回 `python_package.dependencies_not_ready`（409）。公开错误响应使用结构化摘要；组件源码以受信任服务进程权限执行。

创建时先从 `GET /api/python-package-templates/workflow-event-output` 取得精确 `key` 与 `revision`，再提交：

```json
{
  "name": "Workflow 输出",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "内置示例-default",
    "revision": "<catalog revision>"
  }
}
```

endpoint 为 `POST /api/blocks/workflow-event-output`。新建时 folder 必须为空且 revision 必须与 catalog 一致；保存后 package folder 与 `package.json.id` 等于配置 UUID 且不可变，复制时自动跟随新 UUID。
