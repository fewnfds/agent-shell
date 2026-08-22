# 上下文摘要

上下文摘要组件单独配置官方 `SummarizationMiddleware`：在上下文达到阈值时压缩较旧消息，并可在压缩前截断较大的历史工具参数。Main Agent 与 Subagent 可以分别选择、替换或关闭该组件。

选择该组件即启用这份摘要配置，组件内部没有第二个总开关。Main Agent 未选择，或 Subagent 显式选择 `disabled`，才会使用同名 no-op middleware 关闭 Deep Agents 默认摘要行为。

阈值选择“自动”时，运行时保留 Deep Agents 0.7.7 的模型感知默认值：有模型上下文 profile 时按上下文比例计算，
没有 profile 时使用固定 token/消息数。也可以显式选择 fraction、tokens 或 messages 并填写值。

摘要前的原始消息由 Deep Agents 保存在当前运行 Filesystem 的保留 `/conversation_history/{session_uuid}.md`；session UUID 只隔离内部摘要会话。该文件不是客户端 `messages[]`、Lifecycle 对话历史或 Resume 数据，不能通过摘要组件配置路径或文件名。

摘要 Prompt 编辑器默认显示 Deep Agents 内置 Prompt；未修改时仍使用该默认值，点击“还原默认文本”可撤销覆写。
“工具参数截断后的替代文本”是在历史工具参数超过长度阈值时，用来替代被删除内容的文本，不是摘要 Prompt。

编辑器将字段分为三个并列任务区域：摘要触发与保留策略、可选的旧工具参数截断、摘要生成参数与 Prompt。自动阈值不需要填写值；只有选择 fraction、tokens 或 messages 时才显示对应数值输入。
