# Filesystem Permissions

文件系统权限是独立、可复用且非必选的 `filesystem-permissions` Agent capability，通过 `capability_refs` 的 UUID 引用装配。配置块保存权限规则和覆写值，可装配到使用任意[文件系统](filesystem-config.md)的 Agent：

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
- 路径必须从 `/` 开始；反斜杠会先归一为 `/`，不允许包含 `..`、`~` 分段或 NUL；同一配置内 `path` 不得重复，重复提交会被后端拒绝；
- 路径使用 `wcmatch` glob，支持 `*`、`?`、`[]`、`**` 和 `{a,b}`，`/**` 表示递归目录；
- 规则按列表顺序匹配，第一条命中的规则生效；未命中任何规则时默认可读写；
- 合法但没有命中当前文件系统已声明路径的规则只产生 warning，仍可保存和装配；
- `/skills/` 的可见范围与只读边界由系统按 Agent 管理。运行时会在用户规则前固定插入 `/skills/**` 的 allow-read 与 deny-write 规则；由于首条匹配优先，用户规则不能改变该边界。

## 编辑器快捷载入

编辑器可以从任意已保存的 Filesystem 快捷追加虚拟目录和文件路径。快捷载入为目录补 `/**`、为文件使用精确路径，并以 `read-write` 追加；手动新增规则默认 `read-only`。可重复载入不同 Filesystem，重复路径会跳过；它不会保存 source Filesystem ID，也不会建立后续绑定。

## 原子覆写

系统提示词和每个文件工具都是独立覆写点。未启用的点完整沿用 Filesystem 组件；`system_prompt_override: null` 表示未启用并沿用 Filesystem 提示词，启用后提交 `{"value": null}` 则显式使用 Deep Agents 默认 Prompt，二者不同。每个工具覆写点启用后提交完整 `{visible, description_override}`，不做字段级合并；`description_override: null` 表示使用系统默认说明。

`read_file` 固定可见且不可覆写，`execute` 固定不可见且不可覆写；`delete` 默认关闭但可以覆写打开，其余 `ls`、`write_file`、`edit_file`、`glob`、`grep` 默认可见且可覆写。

## Subagent 继承与生效范围

Main Agent 可以选择零或一份文件系统权限。Subagent 默认为 `inherit`，也可 `replace` 为另一配置或以 `disabled` 关闭；关闭后不使用权限配置，回到所选 Filesystem 自身的默认路径规则和工具设置。
同一请求中的 Agent 仍共享 workspace，但各自的规则、提示词和模型可见文件工具独立生效。

权限由 `FilesystemMiddleware` 应用于 `ls`、`read_file`、`write_file`、`edit_file`、`delete`、`glob` 和 `grep`。Custom Tool、MCP 工具、管理台文件管理和宿主进程代码使用各自的权限边界。
