# 上下文摘要

上下文摘要组件单独配置官方 `SummarizationMiddleware`：在上下文达到阈值时压缩较旧消息，并可在压缩前截断较大的历史工具参数。它是可选 capability：Main Agent 不选即不启用；Subagent 默认继承 Main Agent，可显式 `replace` 或 `disabled`。

选择该组件即启用摘要。`truncate_args_enabled` 独立控制历史工具参数截断，默认开启。禁用摘要的 Agent 使用同名 `SummarizationMiddleware` no-op replacement，使每个 Agent 的最终 Middleware stack 保持显式可控。

## 阈值与默认值

`trigger`、`keep`、`truncate_args_trigger` 和 `truncate_args_keep` 四组阈值各自支持 `auto`、`fraction`、`tokens` 或 `messages`。`auto` 不填写 value，并使用当前锁定 Deep Agents 的模型感知默认值；`fraction` 必须在 `(0, 1]`，`tokens` 与 `messages` 必须是正整数。

- `truncate_args_enabled` 默认 `true`；
- `truncate_args_max_length` 默认 `2000` 字符，最小 `1`；
- `truncate_args_text` 默认 `...(argument truncated)`；
- `trim_tokens_to_summarize` 默认 `4000` tokens，最小 `1`，也可为 `null`；
- `summary_prompt_override` 默认 `null`，表示使用 Deep Agents 默认 Prompt。

摘要前的原始消息由 Deep Agents 写入所选 Filesystem 对应 `StateBackend` 的受保护前缀 `/conversation_history/{session_uuid}.md`；session UUID 隔离并行 Agent 的内部摘要会话。该内部文件由 Deep Agents 管理。

摘要 Prompt 编辑器默认显示 Deep Agents 内置 Prompt；未修改时仍使用该默认值，点击“恢复默认 Prompt”可撤销覆写。
“工具参数截断后的替代文本”用于标记超过长度阈值的历史工具参数；摘要 Prompt 单独配置。

编辑器将字段分为三个并列区域：摘要触发与保留策略、工具参数截断、摘要生成参数与 Prompt。自动阈值直接使用模型感知默认值；选择 fraction、tokens 或 messages 时显示对应数值输入。
