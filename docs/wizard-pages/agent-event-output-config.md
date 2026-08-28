# Agent Event Output

Agent Event Output 是 Main Agent 必选组件。Subagent 不能单独配置或覆写该组件，其事件复用所属 Main Agent 的同一个 `output(event)`。它把规范化后的 LangChain v3 Agent 事件交给配置独占的 Python 扩展，函数返回值成为 `/v1/chat/completions` 的文本输出。它不修改 Agent State、提示词或工具。

## 编写 Python 扩展

扩展的 `main.py` 必须提供一个同步入口 `output(event)`；`event` 是下文定义的稳定 `dict`，返回值必须是 `str`。
所有事件类型在同一个函数中按 `event["event_type"]` 分支，返回空字符串表示过滤该事件。

```python
def output(event):
    if (
        event["event_type"] == "assistant_text"
        and event["phase"] == "delta"
    ):
        return event["message"]
    return ""
```

新建配置时可从 `GET /api/python-package-templates/agent-event-output` 加载两个内置示例：`内置示例-default` 按事件选择 Agent 名称、工具名称、Subagent 名称或短状态组成 `details`；`内置示例-assistant-text-only` 只返回 `assistant_text` 的公开答复文本，并用空字符串过滤 reasoning、Tool、Subagent、custom 和 lifecycle 事件。保存后源码复制到配置独占目录，与示例彻底解耦。

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

## 实时正文与首尾文本

`assistant_text`和`reasoning`是 additive phase event。脚本不需要保存状态：`start`返回一次首文本，`delta`返回本次新增正文，`end`返回一次尾文本。下例不会给每个 delta重复添加`<answer>`：

```python
def _stream(event, start="", end=""):
    if event["phase"] == "start":
        return start
    if event["phase"] == "delta":
        return event["message"]
    if event["phase"] == "end":
        return end
    return ""

def output(event):
    if event["event_type"] == "assistant_text":
        return _stream(event, "<answer>", "</answer>")
    if event["event_type"] == "reasoning":
        return _stream(event, "<reasoning>", "</reasoning>")
    return ""
```

模型产生 token stream时，每个真实 delta立即执行`output(event)`。模型只返回完整 block时，投影层机械生成`start -> 单个 delta(完整正文) -> end`；脚本不读取 Model Connection或 Exception Retry配置。为了让 idle yield能够安全关闭并在迟到 delta时重新开启 presentation segment，streaming block开始时会准备同一脚本的 start/end文本，公开写出顺序仍然是 start、delta、end。`output(event)`应是无状态、确定性的文本投影，不修改模块全局状态，也不依赖 start/end函数调用发生的具体时刻。

文字或 reasoning 的`start`和`end`事件中`message`为空；`delta.message`只含本次新增文本。已经收到至少一个真实 delta后，finish完整 snapshot不会再次交给脚本。没有 delta的完整 block使用 snapshot作为上述单个合成 delta。媒体通知仍是一个`assistant_text/end`原子事件，`data["type"]`为`image`、`audio`、`video`或`file`；需要显示媒体通知时应在 phase helper之前单独处理。

## 公共 dict 字段

每类 Agent 事件都包含以下字段；没有来源身份时，相关字符串为空。`data` 是 Python 值（可能是 `dict`、`list`、`ToolMessage` 或 `Command`），不保证 JSON-compatible，不会为了脚本先转成 JSON；需要显示文本时，优先使用当前事件类型已定义的 `message`、`output`、`arguments` 或 `data_json`。

| key | Python 类型 | 含义 |
| --- | --- | --- |
| `event_type` | `str` | 当前事件类型，等于本页事件名 |
| `phase` | `str` | `start`、`delta`、`end` 或 `error` 等语义阶段 |
| `sequence` | `int` | 本次请求内递增的规范化事件序号 |
| `timestamp` | `str` | RFC 3339 UTC 时间 |
| `namespace` | `str` | LangGraph namespace，根作用域为 `root` |
| `agent_name` | `str` | 事件所属 Agent 显示名 |
| `node` | `str` | 产生事件的模型、工具或图节点名 |
| `message` | `str` | 已规范化的主要文本；最常用的默认输出字段 |
| `data` | `object (Python)` | 对应完整语义事件的原始 Python 值，具体类型见下表 |
| `source_type` | `str` | `agent`、`subagent`、`script` 或 `non_agent` |
| `workflow_node_id` | `str` | canvas Workflow Node ID |
| `agent_profile_id` | `str` | Main Agent 配置 UUID |
| `subagent_profile_id` | `str` | Subagent 配置 UUID；非 Subagent 事件为空 |

## 各 Agent 事件 dict

下表中的“附加 key”与全部公共 key 一起出现在该事件的 `event` dict 中。除 `data` 外，附加字段均为 `str`。

| `event_type` | 附加 key | `data` 的 Python 值 |
| --- | --- | --- |
| `assistant_text` | `message_id` | 当前 text block或delta `dict`；媒体通知时为对应媒体 block `dict` |
| `reasoning` | `message_id` | 当前 reasoning block或delta `dict` |
| `tool_call` | `tool_name`, `tool_call_id`, `arguments` | 完整 tool-call content block `dict`；`arguments` 是字符串，结构化参数为紧凑 JSON 文本 |
| `tool_progress` | `tool_name`, `tool_call_id`, `status` | Tool started/output-delta envelope `dict` |
| `tool_result` | `tool_name`, `tool_call_id`, `status`, `output` | 工具返回的 Python 值，可能是 `str`、`dict`、`list`、`tuple`、`ToolMessage` 或 `Command` 中的值；`output` 是规范化文本 |
| `tool_error` | `tool_name`, `tool_call_id`, `status`, `error_code` | 失败的工具事件或无效 tool-call content block `dict` |
| `subagent` | `subagent_name`, `tool_call_id`, `status` | Subagent lifecycle envelope `dict`；某些完成事件为 `None` |
| `custom` | `channel`, `data_json` | custom event 的原始 Python payload；`data_json` 是 JSON 文本 |
| `lifecycle` | `status`, `finish_reason`, `error_code` | lifecycle envelope `dict`，或 Shell 构造的状态 `dict` |

`custom` payload 为 `str` 时，`message` 保持原始字符串，`data_json` 保持带 JSON 字符串引号的合法 JSON 文本。payload 为其他类型时，`message` 与 `data_json` 都使用紧凑 JSON 文本。

`assistant_text`和`reasoning`的 token delta实时执行脚本。其他事件各执行一次。工具调用与可匹配的 terminal结果按同一来源和调用周期配对，并保持一个不可插队的输出项；两者分别执行脚本后再连接，所以任一分支返回空字符串只过滤自己的文本。尚未得到 terminal outcome的 Tool call不会在 Run结束时被调度器擅自补造失败文本或单独公开。

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

Agent Event Output 没有独立事件过滤配置。需要过滤时直接在 `output(event)` 中判断并返回空字符串；空返回值不进入公开响应，也不刷新当前request/node invocation输出原子的空闲倒计时，非空返回值才作为正文进入响应流调度。运行时仍会机械消费必要的content、request和Node terminal控制边界来维护block与atom状态。

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

先从 [`GET /api/python-package-templates/agent-event-output`](../user-guide/ai-guide/01-discover-current-instance.md) 取得精确 `key` 与 `revision`，再提交到 `POST /api/blocks/agent-event-output`。新建时 `python_package.folder` 必须为空，`revision` 必须与 catalog 的目录 sha256 一致；首次保存后服务端生成配置 UUID，package folder 等于配置名称，manifest ID 等于配置 UUID。重命名会同步移动目录，复制会生成新的名称目录和 manifest UUID。
保存后源码位于 current Configuration Repository 的 `data/config_repos/<repository-name>/python_packages/agent_event_output/<configuration-name>/` 独占目录；组件页通过 `GET /api/blocks/agent-event-output/{id}/python-package` 投影后交给 File Manager 编辑。流式与非流式响应消费同一 additive扩展结果，不会从最终 State或 Response Stream policy绕过 Agent Event Output读取原始 Agent内容。另见[Workflow Event Output](workflow-event-output-config.md)。
