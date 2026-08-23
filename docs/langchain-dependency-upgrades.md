# LangChain 系依赖升级

本文记录 LangChain 系依赖的当前维护边界。版本事实仍以 `server/pyproject.toml` 和 `server/uv.lock` 为准；本文说明约束为什么存在，以及下一次升级必须复核什么。

## 当前已审查基线

| 依赖 | 当前版本 | 约束策略 |
| --- | ---: | --- |
| Deep Agents | `0.7.7` | 精确锁定；项目依赖其 middleware 顺序、Filesystem 和 Subagent 行为 |
| LangChain / Core | `1.3.15` / `1.6.0` | 保持当前 major，升级时先复核消息、工具、middleware 和 stream contract |
| `langchain-anthropic` / `langchain-openai` | `1.6.0` / `1.6.0` | LangChain adapter 版本；保持当前 major，按 Provider 分组升级 |
| Google GenAI / Vertex AI | `4.3.4` / `3.2.4` | 各自保持当前 major；model profile 采用上游当前数据 |
| DeepSeek / xAI | `1.1.0` / `1.3.0` | 各自保持当前 major，并与 OpenAI-compatible 路径一起回归 |
| LangGraph / SQLite Checkpoint | `1.2.11` / `3.1.1` | LangGraph 保持 `<1.3.0`，Checkpoint-SQLite 保持 `<4.0`；复核 Graph、stream 和 checkpoint 行为 |
| LangSmith | `0.11.1` | `>=0.11.1,<0.12`，见下方专门说明 |

## LangSmith 约束说明

`langsmith>=0.11.1,<0.12` 是预 1.0 minor 复审边界；升级到新的 minor 时按以下步骤复核：

- `0.11.1` 是已经阅读 release/source diff 并通过本项目直接验证的最低基线；
- LangSmith 仍为 `0.x` 包，下一次 minor 可能改变 tracing、上传或 Client contract，
  因此在未审查前不由普通 resolver 自动跨到 `0.12`；
- 审查 `0.12` 后，应同时把下限更新为已验证版本，并把上限推进到下一个需要复审的 minor；不得继续保留一个已经失去理由的旧上限。

项目使用 LangSmith 的范围很窄：`server/src/agent_shell/langsmith_tracing.py` 在进程启动时构造官方 `Client` 并调用 `langsmith.configure`，由 LangChain/LangGraph 产生标准自动 trace；保存连接设置时使用 `list_projects(limit=1)` 验证 Endpoint、Key 和 Workspace，服务关闭时调用 `Client.close(timeout=5.0)` 刷新并释放资源，连接校验路径的探活 `close()` 为无参调用。该模块同时设置 tracing 环境变量并注册错误回调；升级时一并复核其敏感数据与上传边界。项目没有自建 trace ingestion、直接 `RunTree`、OpenTelemetry、evaluation、pytest plugin 或 Sandbox 集成。

下一次 LangSmith 升级只需围绕上述真实调用面检查：

1. 阅读目标 minor 内全部官方 release notes 和 Python source diff；
2. 检查 `Client`、`configure`、`list_projects`、`close` 以及 LangChain/LangGraph 自动 tracing；
3. 判断上传默认值是否改变 trace 完整性、敏感数据边界、后台资源或关闭刷新行为；
4. 用 scoped resolver 更新 LangSmith，检查 `uv.lock` diff 中目标包及其传递依赖，确认没有未审查的传递依赖变化；
5. 验证 tracing 开关、连接设置原子保存、Client 生命周期和 lock 一致性，然后推进版本边界。

## 通用升级顺序

LangChain 系升级按依赖与影响面分批进行：先 Core/LangGraph contract，再 Provider adapter，
再 Deep Agents，最后 LangSmith。每批使用明确的 `uv lock --upgrade-package <package>`，检查 lock diff 后再同步环境；不要用无范围升级把多个行为面混在一起。

Provider adapter 的 release 如果改变错误内容、协议选择、model profile、token usage、tool call 或 stream block，必须先确定 Shell 的公开失败边界和配置 contract。上游默认行为适合项目时直接采用，不建立重复的 Provider catalog 或兼容分支。
