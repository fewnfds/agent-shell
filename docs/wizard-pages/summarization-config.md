# 上下文摘要

上下文摘要组件单独配置官方 `SummarizationMiddleware`：在上下文达到阈值时压缩较旧消息，并可在压缩前截断较大的历史工具参数。它是可选 capability：Main Agent 不选即不启用；Subagent 默认继承 Main Agent，可显式 `replace` 或 `disabled`。

选择该组件即启用摘要本身，没有第二个摘要总开关；旧工具参数截断另有独立的 `truncate_args_enabled` 开关，默认开启。Main Agent 未选择时，该身份及继承其禁用状态的 Subagent 会进入 `disabled_capabilities`；Subagent 显式 `disabled` 也会进入。两种情况都使用同名 `SummarizationMiddleware` no-op replacement 阻止 Deep Agents 默认回填，保留无行为 placeholder，而不是从 Middleware 列表物理移除。

## 阈值与默认值

`trigger`、`keep`、`truncate_args_trigger` 和 `truncate_args_keep` 四组阈值各自支持 `auto`、`fraction`、`tokens` 或 `messages`。`auto` 不填写 value，并使用当前锁定 Deep Agents 的模型感知默认值；`fraction` 必须在 `(0, 1]`，`tokens` 与 `messages` 必须是正整数。

- `truncate_args_enabled` 默认 `true`；
- `truncate_args_max_length` 默认 `2000` 字符，最小 `1`；
- `truncate_args_text` 默认 `...(argument truncated)`；
- `trim_tokens_to_summarize` 默认 `4000` tokens，最小 `1`，也可为 `null`；
- `summary_prompt_override` 默认 `null`，表示使用 Deep Agents 默认 Prompt。

摘要前的原始消息由 Deep Agents 写入所选 Filesystem 对应 `StateBackend` 的受保护前缀 `/conversation_history/{session_uuid}.md`；session UUID 只隔离并行 Agent 的内部摘要会话。该文件不是客户端 `messages[]`、Lifecycle 对话历史或 Resume 数据，不能通过摘要组件配置路径或文件名。

摘要 Prompt 编辑器默认显示 Deep Agents 内置 Prompt；未修改时仍使用该默认值，点击“恢复默认 Prompt”可撤销覆写。
“工具参数截断后的替代文本”是在历史工具参数超过长度阈值时，用来替代被删除内容的文本，不是摘要 Prompt。

编辑器将字段分为三个并列任务区域：摘要触发与保留策略、可选的旧工具参数截断、摘要生成参数与 Prompt。自动阈值不需要填写值；只有选择 fraction、tokens 或 messages 时才显示对应数值输入。
