# Command Node

Command Node 是 Workflow canvas 上可同时更新 State 和动态选择 successor Node 的 programmable Node。组件配置保存一个独占的 Python 扩展目录引用；
分支不在组件页重复配置，而由画布上从该节点发出的具名 Branch Edge 定义。

## Package 与入口

用户模板位于 `data/templates/workflow/command/<template-key>/`，内置示例位于 `examples/workflow-components/command/<example-key>/`，新建页以 `<key>` 和 `内置示例-<key>` 合并展示。新配置首次保存时复制为 `data/config_repos/<repository-name>/python_packages/command/<configuration-name>/` 下的配置扩展。
配置扩展至少包含 `package.json` 和 `main.py`，模板本身无需 `package.json`，并可包含 `requirements.txt`、本地模块和测试。manifest 固定使用 `family: workflow-node` 与 `adapter: command`。完整目录、manifest、imports 和依赖规则见[文件化 Python 扩展包](../user-guide/middleware-packages.md)。

`main.py` 必须提供同步无参工厂 `create_command()`，返回的 async callable 签名必须恰为 `(state, runtime)`，两个参数都不能有默认值：

```python
def create_command():
    threshold = 80

    async def command(state, runtime):
        risk = state.get("shared_vars", {}).get("risk", 0)
        branch = "manual_review" if risk >= threshold else "continue"
        return {
            "activate": [branch],
            "update": {"shared_vars": {"routed": True}},
        }

    return command
```

新建页选择一份合法用户模板或内置示例。首次保存复制完整模板；已有配置递归显示自己的扩展目录，文件编辑按钮会打开共享文件管理工作区。
新建、上传、下载、重命名、删除和 UTF-8 文本保存都立即作用于私有包。

每个 Command Node 配置都拥有独立的 Python 扩展。复制配置会复制新的扩展目录；模板或其他配置的扩展发生变化都不会影响它。

## Command 返回值

- `state` 是完整 Workflow State 的独立可变副本，当前声明 `shared_vars`、`agent_invocations`、`background_tasks` 和 `files`，只包含本次调用实际存在的 channel；可以修改副本，
  也可以通过 `update` 返回局部更新。
- `runtime` 是 LangGraph 注入的官方 `Runtime[WorkflowRuntimeContext]`。current Run 的 static identity 与 configuration 在 `runtime.context`；Lifecycle
  Store 在 `runtime.store`；background Run 命令在 `runtime.context.background_runs`。脚本通过这些 request-scoped 对象访问运行能力。
- `activate` 必须是 Branch Edge key 列表，可以同时激活多个不同分支；key 必须与画布中选中 Edge 后在属性栏填写的值完全一致，
  不会显示在线段上。
- `update` 必须是 Workflow State 的局部映射；对 `state` 副本的 mutation delta 会与返回的 `update` 合并，后者覆盖同名 key，顶层字段和值的完整形状都按当前 `WorkflowState` contract 校验。
- `activate` 为空或省略时不激活后继目标，只提交 `update`，当前路径在该节点自然结束。
- Shell 不保留兜底 key。条件是否覆盖完整、使用 `if/elif/else` 还是 `match`，由脚本自己负责。
- Branch key 去除首尾空白后必须为 1 至 64 个字符且大小写敏感；返回未知或未连接的 key、重复 key、非法 State field/value、无效 entry 或 exception 都会使 current Workflow Run 失败。

运行时把结果映射为 LangGraph `Command(update=..., goto=[...])`。Branch Edge 只负责声明候选目标，不会再注册为静态 `add_edge`，因此未被 `activate` 选中的分支不会执行。package 不接触 canvas Node ID，也不直接构造或返回 `Command`，由 compiler 负责映射。

这些 Python 代码以服务进程权限执行。源码修改在下一次 Workflow 请求重新加载；
`requirements.txt` 修改后必须重启 Agent Shell，依赖状态才会重新准备。
