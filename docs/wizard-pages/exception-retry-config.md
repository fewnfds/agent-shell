# 异常重试

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

`max_retries` 为非负整数，表示首次失败后的额外请求次数；具体 Provider 可能另有自身限制。可选条件为 transport、timeout、rate limit、
server error 和 authentication error；认证错误默认不选。`force_non_streaming` 同时关闭通用与 Provider
streaming，使失败尝试能在正文公开前重试，但会增加首字延迟。

该组件只处理模型调用异常，不判断回复内容、不实现 fallback model，也不改变 Agent 终止逻辑。
