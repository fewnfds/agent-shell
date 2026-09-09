# Deep Agents 二次开发清单

Agent Shell 当前锁定 `deepagents==0.7.13`。本页集中记录 Agent Shell 在 Deep Agents 公共 API 之上增加、替换或约束的运行时代码，以及每项定制的原因和升级复核条件。依赖版本和完整运行链见 [Deep Agents runtime 基线](deep-agents-migration.md)。

本页所称“二次开发”包括以下边界：

- 为上游缺陷增加的 compatibility middleware；
- 为 Agent Shell 产品配置投影 Deep Agents constructor、SubAgent dictionary、Backend、State 和 Middleware 的适配代码；
- 使用 Deep Agents same-name replacement 或 Harness Profile 改变默认装配结果的代码。

Workflow、Lifecycle、OpenAI-compatible API、输出投影和管理台属于 Agent Shell 自有产品功能，不计入这份 Deep Agents 二次开发清单。

## 维护原则

`server/uv.lock` 安装的 Deep Agents wheel 保持原样。源码、开发虚拟环境和 portable runtime 都不直接修改 `site-packages/deepagents`；portable runtime 会在依赖输入变化时完整重建第三方 `site-packages`。所有定制均保存在 `server/src/agent_shell/`，因此可以被 Git、测试和升级审查稳定追踪。

升级 Deep Agents 前逐项检查下表。上游已经覆盖某项产品需要时，删除对应 Shell 定制及其直接测试；上游公共 contract 仍不能表达产品需要时，按新签名更新同一 owner，不并行保留两套实现。

## 当前清单

| 二次开发点 | 源码 owner | 当前原因 | 升级时复核 |
| --- | --- | --- | --- |
| 空 SystemMessage 兼容 | `runtime/deepagents_compatibility.py`；由 `runtime/agent_builder.py` 和 `runtime/subagents.py` 装配 | Deep Agents `0.7.13` 在无 authored prompt 和无 Harness Profile prompt 时仍向 LangChain 传递 `system_prompt=""`，LangChain 会生成内容为空的第一条 `SystemMessage`。部分 Provider 拒绝该消息。compatibility middleware 在最终 model request 中把这一精确空值投影为 `system_message=None`，非空 prompt 保持原样 | 调用无 `system_prompt` 的 `create_deep_agent()`，捕获 Provider 前的 messages；上游结果不再包含空 system 后删除该 middleware、两个装配点和对应回归测试 |
| Main Agent constructor 投影 | `runtime/agent_builder.py`、`runtime/agent_compilation.py` | 把已校验的模型、工具、Backend、State、Middleware、Subagent 和 response format 收敛为一次官方 `create_deep_agent()` 调用，并把构造失败转换为 Agent Shell 配置诊断 | 核对 `create_deep_agent()` 参数、默认 middleware stack、返回 graph 类型和异常边界 |
| Harness Profile 注册 | `runtime/deepagents_harness.py` | 通过官方 `HarnessProfile` 关闭隐式 `general-purpose` Subagent，使可用同步 Subagent 只来自 Agent Shell 的显式配置关系 | 核对 beta Profile 注册与 merge 语义、provider/model key 解析和 `GeneralPurposeSubagentProfile` 字段 |
| Filesystem 与 Skill 适配 | `runtime/capabilities/deepagents.py` | 依据 Filesystem Backend、Filesystem Tools、mapped directory、Skill package 和权限配置构造官方 Backend、`FilesystemMiddleware`、`SkillsMiddleware` 与 `FilesystemPermission`；`ScopedSkillsBackend` 为 `/skills/` 提供只读 package route | 核对 BackendProtocol、CompositeBackend route、Filesystem/Skills constructor、permission、工具名称、host-path mapping、归档路径和 `glob` 语义 |
| 可选 middleware same-name replacement | `runtime/capabilities/todo_list.py`、`summarization.py`、`prompt_caching.py` | Agent 可以独立启用、继承、替换或关闭能力。关闭时用同名无行为实例占据 Deep Agents 默认 slot，防止默认 stack 回填 | 核对默认 middleware 名称、stack 顺序、replacement 规则、Provider prompt-caching 变体和禁用后的实际 hook 行为 |
| PatchToolCalls 实例接管 | `runtime/agent_compilation.py`；由 `runtime/agent_builder.py` 和 `runtime/subagents.py` 装配 | 使用官方 `PatchToolCallsMiddleware` 实例占据同名默认 slot，让 Main Agent 与 Subagent 的最终 stack 使用当前请求装配的官方 trace policy | 核对默认 stack 是否仍包含该 middleware、constructor 是否变化以及 same-name replacement 是否保留 |
| 同步 Subagent dictionary 与 SubAgentMiddleware replacement | `runtime/subagents.py`、`runtime/subagent_middleware.py` | 把直接子级投影为官方 declarative SubAgent dictionary；需要自定义 task description 时，用同名 `SubAgentMiddleware` 聚合全部公开 `PrivateStateAttr`，保持 delegated state 的 private key 完整 | 核对 SubAgent dictionary fields、isolated/fork mode、task placeholder、state schema、private-state 发现方式和 middleware 继承 |
| Agent State 与首次文件播种 | `runtime/state.py` | `AgentShellState` 在官方 `DeepAgentState` 和 `FilesystemState` 上增加 Shell 私有 channel；`AgentInitialFilesMiddleware` 让固定虚拟文件在每个 Thread 首次运行时只播种一次 | 核对上游 State reducer、FilesystemState、`PrivateStateAttr` 和 `before_agent`/`abefore_agent` contract |
| Provider、Tool 与 model request 边界 | `runtime/limits.py`、`runtime/model_request_settings.py` | 使用官方 sync/async wrapper hook 分类 Provider/Tool 异常，并通过 `ModelRequest.override()` 注入每个模型配置的 `tool_choice` 与 `model_settings` | 核对 `ModelRequest` 字段、`override()`、sync/async hook 配对、wrapper 顺序和 Provider 原生字段 |
| Custom Middleware 接入 | `middleware_packages/runtime.py`、`runtime/agent_builder.py`、`runtime/subagents.py` | 将配置 package 返回的一个官方 `AgentMiddleware` 实例放入 Main Agent 或 Subagent 的 caller middleware slot，并校验工具名、middleware 名和 sync/async hook 配对 | 核对 User slot 位置、重复名称规则、middleware state schema 与工具注入 contract |

## 空 SystemMessage 上游记录

Deep Agents [PR #4859](https://github.com/langchain-ai/deepagents/pull/4859) 将 SDK 的默认 authored prompt 设为空。后续 [Issue #4977](https://github.com/langchain-ai/deepagents/issues/4977) 与 [PR #4989](https://github.com/langchain-ai/deepagents/pull/4989) 明确记录了空 authored prompt 的设计，但没有区分“不发送 system message”和“发送内容为空的 system message”。`0.7.13` 的 `graph.py` 仍执行以下传递：

```python
base_prompt = _apply_profile_prompt(_profile, "")
if system_prompt is None:
    final_system_prompt = base_prompt

return create_agent(..., system_prompt=final_system_prompt)
```

Agent Shell 的 compatibility middleware 只处理 `SystemMessage.content == ""`。Filesystem、Skill、Memory、Harness Profile 或 Custom Middleware 产生的非空 system content 会继续发送；用户选择的非空 System Prompt 也保持原值。

直接回归测试位于 `test/runtime/test_deepagents_compatibility.py`，Main Agent 与 Subagent 装配顺序由 `test/runtime/test_agent_middleware_order.py` 保护。

## 升级步骤

1. 阅读 Deep Agents release notes，并比较锁定 tag 与目标 tag 的 `graph.py`、Backend、Middleware 和 profile API。
2. 按“当前清单”的升级复核列逐项判断保留、调整或删除；先删除已经由上游满足的 compatibility code。
3. 更新 `server/pyproject.toml` 与 `server/uv.lock`，随后更新 [开发与版本](development-and-release.md) 中的依赖基线和第三方声明。
4. 运行本页列出的直接测试以及此次升级实际影响面的一个最接近行为测试。
5. 复核目标 diff 与 `git diff --check`，确认不存在对生成目录或 `site-packages` 的手工修改。
