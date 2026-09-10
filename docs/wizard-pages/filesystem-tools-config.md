# Filesystem Tools

【文件系统工具】是 Main Agent 和 Subagent 的可选 capability。它独立于[文件系统后端](filesystem-config.md)，负责选择模型可见的 Deep Agents 文件工具、覆写工具说明并配置执行参数：

```json
{
  "name": "开发工具",
  "tool_token_limit_before_evict": 20000,
  "human_message_token_limit_before_evict": 50000,
  "grep_max_count": 1000,
  "max_execute_timeout": 120,
  "tool_configs": {
    "ls": {"visible": true, "description_override": null},
    "read_file": {"visible": true, "description_override": null},
    "write_file": {"visible": true, "description_override": null},
    "edit_file": {"visible": true, "description_override": null},
    "delete": {"visible": false, "description_override": null},
    "glob": {"visible": true, "description_override": null},
    "grep": {"visible": true, "description_override": null},
    "execute": {"visible": false, "description_override": null}
  }
}
```

`read_file` 是 Deep Agents FilesystemMiddleware 的必选工具，始终可见。`delete` 与 `execute` 默认关闭，其他文件工具默认开启。`description_override=null` 保留 Deep Agents 的默认工具说明。

`execute` 只有在所选 Backend 是 LocalShellBackend 时可用；与 CompositeBackend 组合会产生装配 error，并阻止正式保存。开启 `execute` 不要求再额外选择 read tool，因为 `read_file` 已由 contract 固定开启。Agent Shell 不提供另一套 Shell 选择器：`execute` 是 Deep Agents FilesystemMiddleware 的官方工具，命令、工作目录与超时参数都按其 Tool schema 传入，底层由 LocalShellBackend 以真实 workspace 为默认工作目录直接在宿主机执行。该执行没有 sandbox，`virtual_mode=True` 只约束文件工具，不能阻止命令访问 Agent Shell 服务账号可达的 workspace 外路径或其他宿主资源。

`tool_token_limit_before_evict` 与 `human_message_token_limit_before_evict` 是大结果卸载阈值，正整数表示阈值，`null` 表示关闭对应卸载。`grep_max_count` 是 grep 默认结果上限；`max_execute_timeout` 是 execute 允许请求的最大秒数，默认值为 120。

Filesystem Tools 必须与一份 Filesystem Backend 同时选择；Tools 单独存在会产生装配 error。Main Agent 可以两者都不选；Subagent 默认分别继承，也可替换或关闭。Backend 带 Skill Package 或 filesystem system prompt override 时不能关闭 Tools。最终 Backend 与 Tools 都存在时，运行时才为该 Agent 装配 FilesystemMiddleware；没有它时，大结果不做文件卸载而是直接进入消息上下文。
