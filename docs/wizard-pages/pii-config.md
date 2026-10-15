# PIIMiddleware (`pii`)

在【代理组件 / PIIMiddleware】创建规则组件，再由 Main Agent 的 capability selector 选择。API 使用 `/agent-shell/api/blocks/pii`，配置随引用它的 Agent 或 Workflow Configuration Bundle 导出、预检和导入。

一个组件保存有序 `rules`，每条规则装配一个 LangChain 官方 `PIIMiddleware`。新组件包含一条 `email/redact` 规则；Agent 的组件选择默认留空。

```json
{
  "name": "Context PII",
  "rules": [
    {
      "pii_type": "email",
      "strategy": "redact",
      "detector": null,
      "apply_to_input": true,
      "apply_to_output": false,
      "apply_to_tool_results": false
    }
  ]
}
```

| 字段 | 有效值与默认值 |
| --- | --- |
| `rules` | 至少一条，可调整顺序，没有产品最大条数 |
| `pii_type` | 默认 `email`；内置类型为 `email`、`credit_card`、`ip`、`mac_address`、`url`，也可填写自定义非空名称 |
| `strategy` | `block`、`redact`、`mask`、`hash`，默认 `redact` |
| `detector` | 默认 `null`，使用内置检测；自定义类型必须填写有效 Python regex。文本按原样保存，首尾空白也属于正则 |
| `apply_to_input` | 默认 `true`，在 `before_model` 处理最近一条 HumanMessage |
| `apply_to_output` | 默认 `false`，在 `after_model` 处理最近一条 AIMessage，并注册官方 v3 stream transformer |
| `apply_to_tool_results` | 默认 `false`，在 `before_model` 处理最近一次 AIMessage 后的 ToolMessage，并注册官方 stream transformer |

同一组件的 `pii_type` 必须唯一，因为 LangChain 的 Middleware name 是 `PIIMiddleware[pii_type]`，Agent stack 要求名称唯一。内置类型也可以使用 regex 覆写 detector。Python callable detector 由已有 Custom Middleware 包使用官方 API 定义。

`detector` 和其他规则参数作为普通组件配置持久化，并进入 Lifecycle configuration snapshot 和 Configuration Bundle。

`redact` 使用 `[REDACTED_TYPE]` 占位符；`mask` 显示局部内容；`hash` 使用官方确定性 hash 表示；`block` 抛出 `PIIDetectionError`，本次调用失败并进入现有运行错误和诊断路径。策略和检测结果以锁定版本 LangChain 为准。Regex 语法错误、自定义类型缺少 detector、空规则数组和重复类型由后端校验返回字段 issue。

Main Agent 使用 `capability_refs` 引用一个 `pii` Component。Subagent 使用现有 `settings.capability_overrides`：没有条目时继承；`{"type":"pii","mode":"replace","block_id":"<UUID>"}` 使用自己的组件；`{"type":"pii","mode":"disabled"}` 关闭。每个 Agent 根据最终配置创建独立 Middleware 实例。输入 hook 排在 Summarization 之前。

## 流式输出与资源代价

开启任意输出侧检测时，官方 transformer 处理 v3 消息、Tool 事件和 State snapshot；这些事件面由当前官方实现共同处理。官方流式检测使用有限 lookback，可能延后首个可见字符；跨片段检测的增量文本和 `content-block-finish` 完成快照可能不完全一致。管理台使用官方消息 reducer，以完成快照更新消息。内置 Agent Event Output 模板消费完成快照中尚未输出的尾部。

需要逐字一致的 OpenAI-compatible append-only 输出时，把该 Agent 使用的 Model Connection 的 `provider_settings.streaming` 设为 `false`；项目会传入官方 `disable_streaming=True`，整条模型消息完成后再输出。Custom Middleware 动态选择其他模型时，也应在该模型使用这个官方设置。仅开启输入检测时，可以按正常模型设置流式输出。

每条规则会扫描对应文本，规则数量、正则复杂度和消息长度影响 CPU 与等待时间；输出暂存和非流式模型调用增加首段等待与内存使用。产品不设置规则数、文本长度或 regex 耗时上限，用户根据自己的任务选择规则。

## 保存边界

规则处理当前 Agent hook 或官方事件所见的消息。Shell 请求入口原文、历史 checkpoint、system prompt、Tool artifact、Provider HTTP 原始响应和日志各自遵循其保存 owner。凭据与导出内容的唯一保护声明见[数据分类与错误披露](../security-and-deployment.md#数据分类与错误披露)。配置在 Lifecycle 创建时冻结；编辑组件影响之后创建的 Lifecycle。

官方参考：[PII detection](https://docs.langchain.com/oss/python/langchain/middleware/built-in#pii-detection)、[Middleware stream transformers](https://docs.langchain.com/oss/python/langchain/event-streaming#register-transformers-on-middleware)、[Disable streaming](https://docs.langchain.com/oss/python/langchain/streaming#disable-streaming)。
