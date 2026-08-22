# Prompt 缓存

Prompt 缓存组件单独配置 Anthropic `Prompt caching middleware`。Main Agent 与 Subagent 可以分别选择、替换或关闭，
后端为每个身份显式物化 middleware，不依赖 Subagent 自动继承 Main Agent 的实例。

TTL 支持 `5m` 和 `1h`，并可设置启用缓存前的最少消息数。它按 `anthropic` Provider 适配器识别：非 Anthropic Provider 仍可完成装配，但中间件会跳过不支持的请求，不修改消息。
