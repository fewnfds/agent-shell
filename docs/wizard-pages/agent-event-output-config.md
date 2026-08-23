# Agent 事件输出

Agent 事件输出是 Main Agent 必选组件。Subagent 不能单独配置或覆写该组件，其事件复用所属 Main Agent 的同一个 `output(event)`。它把规范化后的 LangChain v3 Agent 事件交给配置独占的 Python 扩展，函数返回值成为 `/v1/chat/completions` 的文本输出。它不修改 Agent State、提示词或工具。

## 编写 Python 扩展

扩展的 `main.py` 必须提供一个同步入口 `output(event)`；`event` 是下文定义的稳定 `dict`，返回值必须是 `str`。
所有事件类型在同一个函数中按 `event["event_type"]` 分支，返回空字符串表示过滤该事件。

```python
def output(event):
    if event["event_type"] == "assistant_text":
        return event["message"]
    return ""
```

新建配置时可从 `GET /api/python-package-templates/agent-event-output` 加载内置示例。示例按事件选择 Agent 名称、工具名称、
Subagent 名称或短状态组成 `details`；保存后源码复制到配置独占目录，与示例彻底解耦。

例如自行拼接工具结果：

```python
def output(event):
    if event["event_type"] != "tool_result":
        return ""
    tool = event["tool_name"]
    return f"<tool>{tool}: {event['output']}</tool>"
```

函数签名必须恰好是 `def output(event)`：不接受 `async def`、额外参数、默认参数、`*args` 或 `**kwargs`。脚本异常或返回非字符串会以 `event_output.execution_failed`（502）终止本次运行；声明了尚未就绪的 `requirements.txt` 依赖时，请求期返回 `python_package.dependencies_not_ready`（409）。两类错误均不回显 traceback 或事件正文。
扩展以受信任服务进程的权限运行。可在配置目录的 `requirements.txt` 声明受支持的第三方依赖；依赖变更需完成依赖准备，纯 `main.py` 源码改动在下一次请求重新加载。缺省或空的 `requirements.txt` 表示只使用平台核心依赖；source import 其他 package 时逐行声明 direct dependency。

## 公共 dict 字段

每类 Agent 事件都包含以下字段；没有来源身份时，相关字符串为空。`data` 是 Python 值（可能是 `dict`、`list`、`ToolMessage` 或 `Command`），不保证 JSON-compatible，不会为了脚本先转成 JSON；需要显示文本时，优先使用当前事件类型已定义的 `message`、`output`、`arguments` 或 `data_json`。

| key | Python 类型 | 含义 |
| --- | --- | --- |
| `event_type` | `str` | 当前事件类型，等于本页事件名 |
| `phase` | `str` | `start`、`end` 或 `error` 等语义阶段 |
| `sequence` | `int` | 本次请求内递增的规范化事件序号 |
| `timestamp` | `str` | RFC 3339 UTC 时间 |
| `namespace` | `str` | LangGraph namespace，根作用域为 `root` |
| `agent_name` | `str` | 事件所属 Agent 显示名 |
| `node` | `str` | 产生事件的模型、工具或图节点名 |
| `message` | `str` | 已规范化的主要文本；最常用的默认输出字段 |
| `data` | `object (Python)` | 对应完整语义事件的原始 Python 值，具体类型见下表 |
| `source_type` | `str` | `agent`、`subagent`、`script` 或 `non_agent` |
| `workflow_node_id` | `str` | 画布 Workflow Node ID |
| `agent_profile_id` | `str` | Main Agent 配置 UUID |
| `subagent_profile_id` | `str` | Subagent 配置 UUID；非 Subagent 事件为空 |

## 各 Agent 事件 dict

下表中的“附加 key”与全部公共 key 一起出现在该事件的 `event` dict 中。除 `data` 外，附加字段均为 `str`。

| `event_type` | 附加 key | `data` 的 Python 值 |
| --- | --- | --- |
| `assistant_text` | `message_id` | 完整 text content block `dict`；媒体通知时为对应媒体 block `dict` |
| `reasoning` | `message_id` | 完整 reasoning content block `dict` |
| `tool_call` | `tool_name`, `tool_call_id`, `arguments` | 完整 tool-call content block `dict`；`arguments` 是字符串，结构化参数为紧凑 JSON 文本 |
| `tool_result` | `tool_name`, `tool_call_id`, `status`, `output` | 工具返回的 Python 值，可能是 `str`、`dict`、`list`、`tuple`、`ToolMessage` 或 `Command` 中的值；`output` 是规范化文本 |
| `tool_error` | `tool_name`, `tool_call_id`, `status`, `error_code` | 失败的工具事件或无效 tool-call content block `dict` |
| `subagent` | `subagent_name`, `tool_call_id`, `status` | Subagent lifecycle envelope `dict`；某些完成事件为 `None` |
| `custom` | `channel`, `data_json` | custom event 的原始 Python payload；`data_json` 是 JSON 文本 |
| `lifecycle` | `status`, `finish_reason`, `error_code` | lifecycle envelope `dict`，或 Shell 构造的状态 `dict` |

`assistant_text` 和 `reasoning` 的 token delta 会先缓冲。脚本只在完整语义 block 到达时执行一次，不能依赖每个 token 调用一次 `output()`。工具调用与可匹配的结果仍按同一来源和调用周期配对，并保持相邻输出。返回空字符串只过滤配对后的渲染文本，不会让该事件绕过整流；因此 `tool_call` 即使最终被过滤，也可能先等待匹配的结果或调用周期边界。

## 读取 `data`

`data` 适合提取结构化值；代码必须按照所选事件实际类型访问。例如工具返回 dict 时：

```python
def output(event):
    if event["event_type"] != "tool_result":
        return ""
    result = event["data"]
    return str(result["answer"])
```

如只需要兼容不同 Provider 的公开文本，优先使用已规范化的 `message`、`arguments` 或 `output`。

## 过滤与保存结构

Agent 事件输出没有独立事件过滤配置。需要过滤时直接在 `output(event)` 中判断并返回空字符串；非空返回值才进入响应。

```json
{
  "name": "普通文本",
  "python_package": {"folder": ""},
  "python_package_template": {
    "key": "内置示例-default",
    "revision": "<catalog revision>"
  }
}
```

先从 [`GET /api/python-package-templates/agent-event-output`](../user-guide/ai-guide/01-api-and-discovery.md) 取得精确 `key` 与 `revision`，再提交到 `POST /api/blocks/agent-event-output`。新建时 `python_package.folder` 必须为空，`revision` 必须与 catalog 的目录 sha256 一致；首次保存后服务端生成配置 UUID，并令 package folder、manifest ID 与配置 UUID一致且不可变，复制时自动跟随新 UUID。
保存后源码位于当前 Repository 的 `data/configuration-repositories/<repository-uuid>/python_package_instances/agent-event-output/<configuration-uuid>/` 独占目录；组件页通过 `GET /api/blocks/agent-event-output/{id}/python-package` 投影后交给 File Manager 编辑。流式与非流式响应消费同一扩展结果，不会从最终 State 绕过 Agent 事件输出读取原始 Agent 内容。另见[Workflow 事件输出](workflow-event-output-config.md)。
