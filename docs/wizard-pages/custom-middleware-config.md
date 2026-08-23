# 自定义 Middleware

每份自定义 Middleware 配置拥有一个独占的 `agent-middleware` Python 扩展：

```yaml
name: Request Middleware
python_package:
  folder: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa
```

新建配置时，可以从 `data/templates/agent/custom_middleware/<template-key>/` 加载用户模板，也可以选择 `examples/agent-components/custom-middleware/<example-key>/` 提供的 `内置示例-<example-key>`。用户模板与内置示例可以同名。
首次保存会复制所选模板的完整目录到 `data/configuration-repositories/<repository-uuid>/python_package_instances/agent-middleware/<configuration-uuid>/`，生成属于该配置的 `package.json` 和文件夹引用；文件夹名与 `package.json.id` 都等于配置 UUID。此后配置只读取、
编辑自己的扩展代码目录，模板修改不会传播。

已保存配置会递归显示私有扩展目录中的全部文件。点击文件的编辑按钮会打开共享文件管理工作区，可继续创建、上传、下载、
重命名、删除或编辑 UTF-8 文本；文件修改立即落盘，文本保存带 revision 乐观锁，旧 revision 冲突时需重新载入或确认覆盖。

`main.py` 必须提供同步的 `create_middleware` 工厂，并且只返回一个官方 LangChain `AgentMiddleware`。工厂参数不由 Agent Shell 固定；运行时按参数名提供当前可用的 `agent`/`owner`、`package`/`package_id`、`block`、`assembly`、`backend`、`config`/`blocks`、`references`、`scope`、`workflow_node_id`、`request_id`、`model` 和 `tools` 等值，也可以使用 `**kwargs` 接收全部值。未声明的参数不会注入，缺失必填参数会使装配失败。一个 Middleware 类可以实现多个官方 hook；这些 hook 属于同一个实例，不单独排序。这里的 `agent` 是包含 `id`、`type`、`name`、`package_id` 的 Agent Shell 身份字典，
不是 LangChain Agent 对象。若覆盖 `before_agent`、`before_model`、`after_model`、`after_agent`、`wrap_model_call` 或 `wrap_tool_call` 的同步 hook，必须同时覆盖对应的 async hook，否则装配失败。
目录结构、扩展模板/配置扩展生命周期、依赖与安全边界见[文件化 Python 扩展](../user-guide/middleware-packages.md)。

每份 Custom Middleware 配置只定义一个 Middleware。Main Agent 和 Subagent 分别保存自己的有序 `middleware_refs`，按列表顺序装配多个配置；它不再进入 capability 的继承、替换或关闭规则。复制该组件会同时复制新的扩展代码目录。

排序遵循 LangChain 官方 middleware 列表语义：`before_*` 按列表从前到后执行，`after_*` 按列表从后到前执行，
`wrap_*` 按列表形成嵌套调用。管理台调整的是 Middleware 实例顺序，不对同一实例内部的多个 hook 分别排序。

Workflow Input Context 现在只是内置 Custom Middleware 示例。它没有单独的配置页面或装配顺序；从 `内置示例-workflow-input-context` 创建配置后，直接编辑 `main.py` 中的集中配置和变换函数。概念与运行边界见[Workflow Input Context](../user-guide/workflow-input-context.md)。模板选择器的 `内置示例-` 是展示前缀，实际目录名仍是 `<example-key>`。
