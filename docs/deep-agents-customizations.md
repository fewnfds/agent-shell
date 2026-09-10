# Deep Agents 公共组件接入清单

Agent Shell 当前锁定 `deepagents==0.7.13`。本页记录 Agent Shell 在 Deep Agents
公共 Backend、Middleware 和 State API 之上的适配代码，以及升级时必须复核的边界。
完整装配链见 [LangChain Agent runtime 基线](langchain-agent-runtime.md)。

## 维护原则

`server/uv.lock` 安装的 Deep Agents wheel 保持原样。源码、开发虚拟环境和 portable
runtime 均不直接修改 `site-packages/deepagents`。所有适配位于
`server/src/agent_shell/`，可由 Git、测试和升级审查追踪。

Main Agent root 使用 `langchain.agents.create_agent()`。Deep Agents 组件按当前 Agent
配置逐项构造，并进入 Agent Shell 拥有的固定 middleware slot。新增的上游默认组件不会
自动进入 root stack；产品需要采用它时，应建立真实配置或固定运行 contract，再加入唯一
assembler 与直接测试。

## 当前清单

| 接入点 | 源码 owner | 当前职责 | 升级时复核 |
| --- | --- | --- | --- |
| Root constructor 投影 | `runtime/agent_builder.py`、`runtime/agent_compilation.py` | 将已校验的 model、Tool、State、Store、完整 middleware 和 response format 收敛为一次官方 `create_agent()` 调用，并映射构造错误 | `create_agent()` 签名、State schema、返回 graph、metadata、stream transformer 与异常边界 |
| Filesystem 与 Skill | `runtime/capabilities/deepagents.py` | 依据 Backend、Filesystem Tools、mapped source、Skill package 和权限构造官方 Backend、`FilesystemMiddleware`、`SkillsMiddleware` 与 `FilesystemPermission` | BackendProtocol、Composite route、middleware constructor、permission、Tool surface、host-path mapping、归档路径和 `glob` |
| 增强 Summarization | `runtime/capabilities/summarization.py` | 使用 Deep Agents 的模型感知默认值、归档 Backend、阈值与 Tool 参数裁剪 | defaults、threshold schema、归档路径、State 和 trace policy |
| PatchToolCalls | `runtime/agent_compilation.py` | 为 Main Agent 和 child 显式构造官方 `PatchToolCallsMiddleware` | constructor、repair 行为、State 和 trace policy |
| 同步 Subagent | `runtime/subagents.py`、`runtime/subagent_middleware.py` | 投影 declarative dictionary，显式构造 `SubAgentMiddleware`，并聚合全部公开 `PrivateStateAttr` | dictionary fields、dynamic response schema、isolated/fork mode、task placeholder、child compiler、State schema 与 private-state 发现方式 |
| child 空 SystemMessage 兼容 | `runtime/deepagents_compatibility.py`、`runtime/subagents.py` | declarative child 未配置 prompt 时，将精确的空 `SystemMessage` 投影为 `None`；非空内容保持 | `create_sub_agent()` 对缺省 `system_prompt` 的处理；上游不再生成空消息后删除兼容层及直接测试 |
| Agent State 与首次文件播种 | `runtime/state.py` | `AgentShellState` 组合 `DeepAgentState` 与 `FilesystemState`；`AgentInitialFilesMiddleware` 在 Main Agent Thread 首次运行时播种固定虚拟文件 | reducer、FilesystemState、`PrivateStateAttr` 与 before-agent hook contract |
| Provider、Tool 与 model request 边界 | `runtime/limits.py`、`runtime/model_request_settings.py` | 使用官方 sync/async wrapper hook 分类异常，并通过 `ModelRequest.override()` 注入模型请求设置 | `ModelRequest` 字段、wrapper 顺序、sync/async hook 与 Provider 原生字段 |
| Custom Middleware | `middleware_packages/runtime.py`、`runtime/agent_builder.py`、`runtime/subagents.py` | 将配置 package 返回的官方 `AgentMiddleware` 按引用顺序加入 Shell-owned package slot，校验 Tool/Middleware 名称及 hook 配对 | middleware State schema、Tool 注入、wrapper/hook 顺序和 package context |

## declarative child 的空提示词

Deep Agents `0.7.13` 的 `create_sub_agent()` 使用：

```python
create_agent(
    model,
    system_prompt=spec.get("system_prompt", ""),
    tools=spec["tools"],
    middleware=middleware,
)
```

因此 Agent Shell 在 child stack 中装配 `EmptySystemMessageMiddleware`。它只处理
`SystemMessage.content == ""`；Filesystem、Skill、SubAgent 或 Custom Middleware
产生的非空 system content，以及用户选择的非空 System Prompt，都会继续发送。
Main Agent 直接把未选择的 prompt 表达为 `system_prompt=None`。

直接回归测试位于 `test/runtime/test_deepagents_compatibility.py`；Main/child 的完整
middleware 顺序由 `test/runtime/test_agent_middleware_order.py` 保护。

## 升级步骤

1. 阅读 LangChain 与 Deep Agents release notes，并比较锁定版本的 `create_agent()`、
   `create_sub_agent()`、Backend、Middleware 和 State 公共 API。
2. 按“当前清单”逐项判断保留、调整或删除；上游已满足产品需要时删除对应适配和测试。
3. 更新 `server/pyproject.toml` 与 `server/uv.lock`，随后更新
   [开发与版本](development-and-release.md) 的依赖基线和第三方声明。
4. 运行直接装配测试，以及此次升级真实影响面的一个最接近行为测试。
5. 复核目标 diff 与 `git diff --check`，确认没有手工修改生成目录或 `site-packages`。
