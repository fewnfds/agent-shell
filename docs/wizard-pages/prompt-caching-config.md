# Prompt Caching

Prompt 缓存组件单独配置 Anthropic `Prompt caching middleware`。Main Agent 与 Subagent 可以分别选择、替换或关闭，
后端为每个身份显式物化 middleware，不依赖 Subagent 自动继承 Main Agent 的实例。

```json
{
  "name": "Anthropic prompt cache",
  "type": "ephemeral",
  "ttl": "5m",
  "min_messages_to_cache": 0
}
```

`type` 固定为 `ephemeral`。`ttl` 只接受 `5m` 或 `1h`，默认 `5m`；`min_messages_to_cache` 是非负整数，默认 `0`，表示不等待额外消息门槛。

Main Agent 未选择该 capability，或 Subagent 显式保存 `mode: "disabled"` 时，运行时使用同名无行为 middleware 阻止 Deep Agents 默认 Prompt caching 回填。Subagent 未保存 override 时继承 Main Agent，保存 `replace` 时使用另一份配置。

运行时固定构造 `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`。非 Anthropic 模型仍可完成装配；中间件自行跳过不支持的请求，不报错也不修改消息。
