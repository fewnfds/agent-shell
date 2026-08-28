# Exception Retry

`exception-retry` 是 Main Agent 的可选 capability；Subagent 可以继承、替换或关闭它。下面是选择 `model_retry_middleware` 的非默认示例：

```json
{
  "name": "瞬时错误重试",
  "strategy": "model_retry_middleware",
  "force_non_streaming": false,
  "max_retries": 2,
  "retry_on": ["transport_error", "timeout", "rate_limit", "server_error"]
}
```

策略二选一：

- `provider_native`：把 `max_retries` 交给 Provider integration；
- `model_retry_middleware`：关闭 Provider 原生重试并使用 LangChain `ModelRetryMiddleware`。

默认值是 `provider_native`、`max_retries=2`、`force_non_streaming=false`，以及不含认证错误的四项 `retry_on`。`max_retries` 为非负严格整数，表示首次失败后的额外请求次数；具体 Provider 可能另有自身限制。

`retry_on` 只对 `model_retry_middleware` 生效，可选 transport、timeout、rate limit、server error 和 authentication error，且不能重复；`provider_native` 完全使用 Provider integration 的重试判定。认证错误默认不选，只有确认第三方网关会把瞬时故障错误报告为认证失败时才应开启，真实凭据错误不会因重试恢复。

`force_non_streaming` 对两种策略都生效，在 Model Connection设置之后把 Provider `streaming`和 LangChain `disable_streaming`统一覆盖为关闭，使失败尝试能在正文公开前重试，但会增加首字延迟。它不选择哪些事件公开，也不绕过 Agent Event Output；完成的正文仍按同一 additive phase contract投影。

该组件只处理模型调用异常，不判断回复内容、不实现 fallback model。达到 `max_retries` 后仍失败时，错误继续交给上层 Agent/Workflow 错误边界，不改变终止语义。
