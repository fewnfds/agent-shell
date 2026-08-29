# 文件化 Python 扩展

Agent Shell 的文件化 Python 扩展分为扩展模板、配置扩展和组件配置三层：

- 用户模板是 `data/templates/` 下的公共代码资源，只用于创建配置；
- 源码附带的只读示例位于 `examples/`，在模板选择器中使用 `内置示例-<key>` 名称；
- 保存新配置时，系统把所选模板复制成由该配置独占的 Python 扩展；
- 配置扩展位于当前 `data/config_repos/<repository-name>/python_packages/`，复制完成后与原模板彻底解耦；
- 组件 YAML 只保存扩展代码目录引用。

模板和内置示例都不会被直接导入、执行或收集依赖。修改或删除来源不会影响已经保存的配置；模板和配置扩展各自独立维护。
内置示例不会写入 `data/`；管理员可以通过顶层【文件管理】进入 `data/templates/`，或直接在对应类别下维护用户模板，目录为空也是合法状态。用户模板可以与内置示例同名，catalog key 分别为 `<key>` 和 `内置示例-<key>`。

## 目录类别

```text
data/
  templates/
    workflow/command/<template-key>/
    workflow/workflow_event_output/<template-key>/
    agent/custom_tool/<template-key>/
    agent/custom_middleware/<template-key>/
    agent/agent_event_output/<template-key>/
  config_repos/<repository-name>/
    components/<type>/<configuration-uuid>.yaml
    python_packages/
      command/
        <configuration-name>/
      workflow_event_output/
        <configuration-name>/
      agent_tool/
        <configuration-name>/
      agent_middleware/
        <configuration-name>/
      agent_event_output/
        <configuration-name>/

examples/
  workflow-components/command/<example-key>/
  workflow-components/workflow-event-output/<example-key>/
  agent-components/custom-tool/<example-key>/
  agent-components/custom-middleware/<example-key>/
  agent-components/agent-event-output/<example-key>/
```

模板至少包含 `main.py`，可以包含 `requirements.txt`、本地模块、测试和随源码分发的目录；第三方依赖仍需在 `requirements.txt` 中逐行声明。
模板目录名 `template-key` 长 1 至 64 个字符，只使用小写字母、数字、`_` 和 `-`，并以字母或数字开头、结尾。模板没有 package UUID，也不属于任何配置。

配置扩展至少包含 `package.json` 和 `main.py`。文件夹名等于拥有它的 Component 配置名称，`package.json.id` 等于该 Component UUID。
系统通过名称目录引用和 manifest UUID 校验拒绝配置引用其他配置的扩展代码目录；名称改动会同步移动目录，但不会改变 UUID 身份和引用。

## Manifest

模板没有 manifest；所属目录类别决定 `family` 和 `adapter`。保存新配置时，系统生成实例自己的 `package.json`：

```json
{
  "format_version": 1,
  "family": "workflow-node",
  "adapter": "command",
  "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
}
```

`package.json` 承担配置 UUID 与 adapter 身份校验。文件管理会把它与私有包中的其他文件一同显示；修改后如果身份或格式不合法，
组件刷新、装配和运行校验会报告问题。

## 配置引用

Command Node 和 Custom Middleware 使用同一 YAML 外壳：

```yaml
python_package:
  folder: My Command
```

YAML 保存配置字段和私有包引用；源码、requirements 与 manifest 位于私有包目录。创建时提交的模板 `key/revision` 用于检测模板目录并发变化。复制组件配置时会复制一份新的配置扩展；删除组件配置时会删除其扩展代码目录。

新配置编辑器同时读取对应类别的用户模板和内置示例。选择其中一项后，首次保存复制完整模板并生成配置 UUID 与 `package.json`。需要空白起点时，先在 `data/templates/` 中创建符合对应 adapter 要求的最小模板。

已有配置显示私有包中的全部相对文件路径。点击编辑会打开共享文件管理工作区并进入文件所在目录；文件正文、新文件、目录、
上传、下载、重命名和删除都在该工作区中立即落盘，不依赖组件表单保存。UTF-8 文本保存使用单文件内容 revision；磁盘文件发生变化后，
旧 revision 的保存会被拒绝，页面保留草稿并允许重新载入或确认覆盖最新内容。文件编辑期间不持有磁盘锁。

## Command Node

Command 使用 `family: workflow-node`、`adapter: command`。同步工厂返回固定签名的 async callable：

```python
def create_command():
    threshold = 80

    async def command(state, runtime):
        risk = state.get("shared_vars", {}).get("risk", 0)
        items = state.get("shared_vars", {}).get("items", [])
        branch = "review" if risk >= threshold else "continue"
        return {
            "activate": [branch],
            "dispatch": [
                {
                    "task_id": f"item:{item['id']}",
                    "dispatch_key": "item",
                    "payload": {"item": item},
                }
                for item in items
            ],
            "update": {
                "shared_vars": {
                    "dispatched_count": len(items),
                }
            },
        }

    return command
```

`command(state, runtime)` 返回 `activate`、`dispatch` 和 `update`，三个字段都可以为空。`activate` 选择零个或多个 Branch Edge key；`dispatch` 包含零个或多个 Agent worker task；`update` 是 parent Workflow State 的 partial update。Branch 与 Dispatch 可以在同一次 invocation 中同时产生。

每个 dispatch item 使用同批唯一的 `task_id`、与同源 Dispatch Edge 完全匹配的 `dispatch_key`，以及 strict JSON object `payload`。payload 拒绝 Python 对象和非有限数。compiler 为每项构造 Shell-owned `WorkflowTaskContext`，再映射为 LangGraph `Send`；目标 Agent subgraph 通过 private State 的 `workflow_task` 读取 `command_node_id`、`command_invocation_id`、`task_id`、`dispatch_key` 和 `payload`。同批 `update` 在 parent State reducer 中提交，不会自动进入这些 `Send` 的私有 State，因此 worker 当批需要的材料应直接放入 payload 或通过 reference 读取。

画布 compiler 把完整结果映射为一个 LangGraph `Command`。package 不接触 Edge ID、target Node ID 或 topology，也不直接返回 LangGraph `Command`/`Send`。完整规则与内置示例见 [Command](../wizard-pages/command-config.md)。

## Custom Middleware

Middleware 使用 `family: middleware`、`adapter: agent-middleware`。每个配置的工厂只返回一个官方 `AgentMiddleware`：

```python
from langchain.agents.middleware import ModelCallLimitMiddleware


def create_middleware(agent, config, backend):
    return ModelCallLimitMiddleware(run_limit=20)
```

`create_middleware` 是同步工厂，Agent Shell 不限制它的参数签名。运行时按参数名提供当前可用的构造数据，包括 `agent`/`owner` 身份字典、`package`、`package_id`、`block`、`assembly`、`backend`、`config`/`blocks`、
`references`、`scope`、`workflow_node_id`、`request_id`、`model` 和 `tools` 等；工厂也可以使用 `**kwargs` 接收全部可用值。这些参数是 Agent Shell 的装配投影，部分值会随当前装配范围而为空。工厂返回后，Middleware 通过 LangChain 官方 hook 的 `state` 和 `runtime` 读取每次运行的动态数据。
Main Agent/Subagent 的有序 `middleware_refs` 决定多个实例进入列表的顺序。一个实例可以实现多个官方 hook，但 hook 不作为独立排序项。LangChain 对 `before_*` 正序执行、对 `after_*` 逆序执行，并把 `wrap_*` 按列表嵌套。Agent Shell 不代理官方 hook、state schema、tools 或 stream transformer。运行链使用异步执行；若自定义类覆盖 `before_agent`、`before_model`、`after_model`、`after_agent`、`wrap_model_call` 或 `wrap_tool_call` 中的同步 hook，也必须覆盖对应的 async hook，否则装配会被拒绝。

内置 `agent-additional-prompt` template 通过普通 `AgentMiddleware.abefore_agent` 选择 Workflow 原始输入、Subagent delegated messages 和 Command dispatch task。复制 template 后，在 `build_agent_additional_prompt_messages(state, runtime, request_messages, backend)` 中按 current Agent 的职责选择、裁剪和转换材料，并通过 Agent 的有序 `middleware_refs` 决定位置。完整说明见 [Agent Additional Prompt](agent-additional-prompt.md)。

## Imports 与依赖

Python 名称仍需显式 `import`。本地模块使用正常相对导入，例如 `from .helpers import build_route`。非核心直接依赖逐行写入配置扩展的可选 `requirements.txt`。

`requirements.txt` 可以不存在，也可以是空文件；两者都表示没有额外依赖。只有 source 实际 import 平台核心之外的 third-party package 时才需要新增或填写它。模板和配置 extension 不会因为缺少这个占位文件而失效。

启动器只收集启用 Workflow 可达的配置扩展 requirements：Graph 中的 Command 和 Workflow Event Output，以及可达 Main Agent/Subagent 引用的 Custom Tool、Custom Middleware 和 Agent Event Output。静态模板和未被运行配置触达的扩展不进入依赖指纹，也不影响全局依赖。依赖层生成在 `runtime/python_packages/site-packages/`；requirements 修改后重启生效，Python 源码在下一次请求重新加载。

依赖只接受普通 PyPI requirement、与核心约束兼容且提供 Windows wheel 的版本，不接受 URL、本地路径、`.pth` 或只有源码发行包的依赖。

## 安全

配置扩展是受信任的任意代码，以 Agent Shell 服务进程权限运行。secret 由 Environment/Provider owner 保存。请求级模块使用独立命名空间加载，并在请求结束时从模块缓存清理。
