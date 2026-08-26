# Custom Tool

每个 Custom Tool 配置拥有一个独立 Python extension，并通过 `main.py` 的同步无参工厂导出一个 LangChain Tool：

```python
from langchain_core.tools import tool, BaseTool


@tool
def word_count(text: str) -> int:
    """Count whitespace-separated words in text."""
    return len(text.split())


def create_tool() -> BaseTool:
    return word_count
```

`create_tool()` 必须返回一个 `BaseTool`；推荐使用 LangChain `@tool`。函数名是模型可见 Tool name，docstring 是模型看到的 description，typed parameters 形成 input schema。一个扩展只导出一个 Tool；共享 helper 可以放在同一目录的 local module 中。

用户模板位于 `data/templates/agent/custom_tool/<template-key>/`；首次保存后实例位于 `data/configuration-repositories/<repository-uuid>/python_package_instances/agent-tool/<configuration-uuid>/`，生成的 `package.json` 固定为 `family: tool`、`adapter: agent-tool` 且 `id` 等于配置 UUID。

新建配置时选择一份合法用户模板或内置示例。首次保存会复制模板的完整目录；保存后，组件页列出私有包中的全部文件，点击编辑会打开共享文件管理工作区。只有源码直接 import 第三方包时才在 `requirements.txt` 逐行声明 direct dependency，重启后通过 package inspection 的 `dependency_status` 和 `requirements_fingerprint` 确认。

Main Agent 和 Subagent 分别通过有序 `tool_refs` 装配零个或多个 Custom Tool 配置。两者列表独立，不使用 capability 的 inherit/replace/disabled。运行时按列表顺序调用每个 `create_tool()`，再把得到的 Tool 列表交给 `create_deep_agent(tools=...)`；
重复的模型可见 Tool name（包括 Filesystem 和 `task` 等默认工具）会在 Agent 构建边界被拒绝；Main Agent 使用 `tool_refs: [{"tool_id": "..."}]`，Subagent 使用 `settings.tool_refs`，各列表内的引用必须去重。

完整 package、依赖和 ToolRuntime capability 见[编写 Agent Tool、Middleware 与 hook](../user-guide/ai-guide/04-agent-tools-middleware-hooks.md)。
