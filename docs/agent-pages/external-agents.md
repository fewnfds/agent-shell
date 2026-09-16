# External Agent

External Agent 是 Configuration Repository 中与 Main Agent、Subagent 平级的一类配置实体，保存一个由外部 CLI 承载的 agent 预设。它不进入 LangChain `create_agent()` 装配，不产生官方 Thread 或 Run，也不作为 ChatModel 使用；Command Node 脚本按预设内容组装外部 CLI 的参数。

```json
{
  "name": "Antigravity Reviewer",
  "description": "Reviews a diff and returns findings.",
  "provider": "antigravity-cli",
  "agent_name": "antigravity-reviewer",
  "system_prompt": "You review diffs and answer with findings only.",
  "model": null,
  "effort": "low",
  "print_timeout": "5m",
  "output_format": "stream-json",
  "conversation": "new",
  "exclude_default_components": true,
  "tools": ["view_file", "grep_search"],
  "tool_guidance": "Read files with absolute paths.",
  "tool_permission": "request-review",
  "permission_allow": ["read_file(*)"],
  "env": {}
}
```

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `name` | string | 配置显示名，在 External Agent 作用域内按大小写不敏感方式唯一 |
| `description` | string | 配置说明；物化为外部 CLI 的 agent 描述 |
| `provider` | enum | 外部 CLI 适配器；当前取值为 `antigravity-cli` |
| `agent_name` | string | 外部 CLI 侧该 agent 的标识，必须匹配 `^[a-z][a-z0-9_-]*$` |
| `system_prompt` | string | 该外部 agent 的系统提示词正文 |
| `model` | string \| null | 外部 CLI 的模型 slug；`null` 表示使用该 CLI 的默认模型 |
| `effort` | enum \| null | `low` / `medium` / `high`；`null` 表示使用该 CLI 的默认推理强度 |
| `print_timeout` | string | 单次调用的超时时间，格式为 `<数字><s\|m\|h>` |
| `output_format` | enum | `stream-json` / `json` / `text`；默认 `stream-json`，普通调用固定使用它 |
| `conversation` | enum | `new` 每次建立新会话；`continue-latest` 接续该 HOME 内最近一次会话 |
| `exclude_default_components` | boolean | `true` 时先移除外部 CLI 的内置提示组件与内置工具，再按 `tools` 逐个加回 |
| `tools` | string[] | 允许的工具白名单，取值必须是 Antigravity CLI 的 17 个内置工具名之一；未列出的工具不存在，写错名字在物化期显式失败 |
| `tool_guidance` | string | 追加进 system 提示正文的工具用法说明；排除内置组件后 CLI 不再下发参数说明，需要在此写清关键约束（例如路径必须绝对） |
| `tool_permission` | enum | 外部 CLI 的工具审批姿态：`request-review` / `proceed-in-sandbox` / `always-proceed` / `strict` |
| `permission_allow` | string[] | 外部 CLI 的细粒度放行规则，例如 `read_file(*)`、`command(git)`；与 `tools` 是两层，缺这层时 headless 调用会被自动拒绝 |
| `env` | object | 传给外部进程的普通环境变量；不允许覆盖 `HOME`、`USERPROFILE`、`XDG_CONFIG_HOME`，这三个由运行环境 owner 管理 |

Antigravity CLI 的 `tools` 是**严格白名单**：不写表示不额外限制（在保留内置组件时即全部内置工具），
写了则只有列出的工具存在。`exclude_default_components` 与 `tools` 组合即"先全禁、再逐个放行"，
一个都不列就是纯文本调用。提示词组件没有对应的逐块开关，粒度只有"全部内置"或"一个都不要"。

预设只保存调用参数，不保存 credential；鉴权由外部 CLI 自己从宿主账号读取。配置不暴露采样参数，因为外部 CLI 不提供对应入口。
具体会话 ID 也不进预设：它属于实例运行态、随运行 HOME 变化，调用方按次覆盖 `conversation` 时传入。

## 存储与所有权

每份预设保存为 active Configuration Repository 的 `agents/external/<uuid>.yaml`，与 Main Agent、Subagent 共用全局 UUID4 identity 和名称校验规则，并随 Configuration Bundle 导出与导入。预设的草稿校验通过 `POST /agent-shell/api/validation/draft` 的 `external_agent` target 执行；集合接口为 `/agent-shell/api/external-agents`。

## 页面

管理台【外部 Agent】页面提供预设的新建、编辑、复制与删除。新建预设的第一步是选择 `provider`，字段集由该取值决定；`antigravity-cli` 之外的 provider 在契约层被拒绝，不进入配置。

Main Agent 与 Subagent 都无法引用 External Agent：它们的 `capability_refs`、`tool_refs`、`middleware_refs`、`mcp_refs` 与 `subagents` 只接受其各自声明过的引用类型。Workflow 侧的调用编排见 [Command Node](../wizard-pages/command-config.md)。
