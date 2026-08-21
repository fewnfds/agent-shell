# 文件系统权限

文件系统权限是独立、可复用的 Agent 能力，不保存文件系统 ID。它可以装配到使用任意文件系统的 Agent：

```json
{
  "name": "只读审阅",
  "permissions": [
    {"path": "/source/**", "permission": "read-only"},
    {"path": "/private/**", "permission": "no-access"}
  ],
  "system_prompt_override": {"value": "只读取并审阅文件。"},
  "tool_overrides": {
    "write_file": {"visible": false, "description_override": null}
  }
}
```

## 路径规则

- `permission` 可选 `read-write`、`read-only`、`no-access`；
- 路径必须从 `/` 开始，不允许 `..`、`~` 或 NUL；支持 Deep Agents 的 glob，包括 `**` 和 `{a,b}`；
- 规则按列表顺序匹配，第一条命中的规则生效；未命中任何规则时默认可读写；
- 合法但没有命中当前文件系统已声明路径的规则只产生 warning，仍可保存和装配；
- `/skills/` 的可见范围与只读边界由系统按 Agent 管理，用户规则不能改变。

编辑器可以从任意已保存文件系统快捷追加其虚拟目录和文件路径。快捷载入只填写普通规则，可重复载入不同
文件系统，重复路径会跳过；它不会保存来源文件系统 ID，也不会建立后续绑定。

## 原子覆写

系统提示词和每个文件工具都是独立覆写点。未启用的点完整沿用文件系统组件；启用后使用本组件中的完整值，
不做字段级合并。`read_file` 必须可见，`execute` 固定关闭；`delete` 默认关闭。

Main Agent 可以选择零或一份文件系统权限。Subagent 可以继承、替换或关闭；关闭表示使用默认路径规则和工具设置，
同一请求中的 Agent 仍共享 workspace，但各自的规则、提示词和模型可见文件工具独立生效。

权限只约束 Deep Agents 内置文件工具，不限制自定义工具、MCP 工具或宿主进程代码，也不是操作系统 sandbox。
