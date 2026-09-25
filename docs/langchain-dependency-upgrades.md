# LangChain 系依赖升级

本文记录 LangChain 系依赖的当前维护边界。精确版本以 `server/pyproject.toml`、`server/uv.lock`、`frontend/package.json` 和 `frontend/package-lock.json` 为准。

## 当前基线

| 依赖 | 当前版本 | 约束策略 |
| --- | ---: | --- |
| Deep Agents | `0.7.19` | 精确锁定；项目显式使用其 Filesystem、Skills、Summarization、PatchToolCalls、Subagent、UnsupportedContent、Backend、State 和 trace policy；fork mode 未启用 |
| LangChain / Python Core | `1.4.2` / `1.6.5` | Main Agent root 使用 `create_agent()`；保持当前 major；`langchain.mcp` 是尚未启用的 beta 能力，现有 MCP 继续由 adapters 提供 |
| OpenAI | `1.6.6` | 默认显式使用 Chat Completions；升级时复核 model profile、content block 和错误边界 |
| DeepSeek | `1.1.1` | 自定义 `base_url` 保持原路由；默认 DeepSeek endpoint 的 `strict=True` 使用官方 beta endpoint |
| Google GenAI adapter / Python SDK | `4.4.0` / `2.25.0` | Gemini Developer API（API Key）适配；`google-genai` 由 adapter 引入。升级时复核 `vertexai=False` 强制、API Key 要求、`base_url`/`api_version` 组合、`reasoning_effort`、生成与流式 Tool 声明 |
| Deep Agents 传递依赖 | Anthropic `1.7.4` | 由 Deep Agents `0.7.19` 传递引入，项目不直接维护 |
| MCP adapters / Python SDK | `0.3.2` / `1.30.0` | 当前使用 `MultiServerMCPClient`；远程 Streamable HTTP 使用最终 endpoint URL，SDK 跟随同源或同主机默认端口 HTTP→HTTPS 重定向，POST 要求 307/308；新的 beta `langchain.mcp` 属于独立功能迁移 |
| LangGraph / SQLite checkpoint | `1.2.12` / `3.1.1` | LangGraph 保持 `<1.3.0`，Checkpoint-SQLite 保持 `<4.0` |
| LangGraph Agent Server | API `0.14.4`；runtime `0.34.1`；CLI `0.4.32`；SDK `0.4.5` | API/runtime 按官方协同发布线升级；当前未启用 LangSmith API-key auth、encryption、BYOC logging 或 `cancel_on_disconnect` |
| LangSmith Python SDK | `0.14.0` | `>=0.14.0,<0.15.0`，见下方专门说明；满足当前 Deep Agents 的最低依赖 |
| frontend LangChain | Core `1.2.12`；Vue `1.1.2`；LangGraph SDK `1.11.2` | 当前直接消费 `useStream`、Message、content block 和 Tool call projection；SDK 负责 Thread stream 的重连与恢复 |

## LangSmith 约束说明

`langsmith>=0.14.0,<0.15.0` 是预 1.0 minor 复审边界。项目使用 `Client`、`configure`、`list_projects`、`close` 和标准自动 tracing；multipart 上传重试、trace sample rate 元数据和 OTel 导出由 SDK 实现。项目按 Project 路由追踪，不配置 beta Agent addressing、sandbox 或 evaluate。下一次 minor 继续复核 tracing transport、上传与 Client 生命周期。

## 升级方式

LangChain 系升级按调用链分批进行：LangChain/Core 与直接 Provider adapter 可以组成 Python 主干批次；Deep Agents、底层 Provider SDK、frontend message contract、LangSmith tracing 和 Agent Server 分别独立升级。每批使用 scoped `uv lock --upgrade-package <package>` 或 `npm install --save-exact <package>@<version>`，检查 resolver 带入的传递变化后运行最接近的直接测试，并重新生成 `THIRD_PARTY_NOTICES.md`。

上游发布包含新功能、参数或默认行为变化时，先在阶段报告中说明与项目调用面的关系，再决定是否采用；采用后只维护上游现行 contract，不保留旧版本兼容分支。
