# LangChain 系依赖升级

本文记录 LangChain 系依赖的当前维护边界。精确版本以 `server/pyproject.toml`、`server/uv.lock`、`frontend/package.json` 和 `frontend/package-lock.json` 为准。

## 当前基线

| 依赖 | 当前版本 | 约束策略 |
| --- | ---: | --- |
| Deep Agents | `0.7.24` | 精确锁定；项目显式使用其 Filesystem、Skills、Summarization、PatchToolCalls、Subagent、UnsupportedContent、Backend、State 和 trace policy；Skills 位于 Summarization/Custom Middleware 之后，模型归档观察最终 request；fork mode 未启用 |
| LangChain / Python Core | `1.4.5` / `1.6.10` | Main Agent root 使用 `create_agent()`；保持当前 major；`langchain.mcp` 是尚未启用的 beta 能力，现有 MCP 继续由 adapters 提供 |
| OpenAI | `1.7.1` | 默认显式使用 Chat Completions；Python SDK 锁定 `3.29.0`；项目为 OpenAI/DeepSeek 注入共享 HTTPX `0.28.1` client，使用 SDK 官方迁移期支持的 legacy-client 路径；SDK 同时依赖 HTTPX2，后续升级复核该公开兼容入口、model profile、content block 和错误边界 |
| DeepSeek | `1.1.1` | 自定义 `base_url` 保持原路由；默认 DeepSeek endpoint 的 `strict=True` 使用官方 beta endpoint |
| Google GenAI adapter / Python SDK | `4.4.2` / `2.30.1` | Gemini Developer API（API Key）适配；`vertexai=False`，SDK 默认自动续接 continuation token 并累计 usage；后续 Provider 请求由 SDK 拥有，额外请求产生模型成本；Tool、无 token 的错误和取消保持官方行为 |
| Deep Agents 传递依赖 | Anthropic `1.7.6` | 由 Deep Agents `0.7.24` 传递引入；Python SDK 锁定 `1.13.0`，adapter 的默认 client wrapper 使用 SDK 对应的 HTTPX2 类型；当前 Shell Main Agent Provider 集合为 OpenAI/DeepSeek/Google GenAI |
| MCP adapters / Python SDK | `0.3.2` / `1.30.0` | 当前使用 `MultiServerMCPClient`；远程 Streamable HTTP 使用最终 endpoint URL，SDK 跟随同源或同主机默认端口 HTTP→HTTPS 重定向，POST 要求 307/308；新的 beta `langchain.mcp` 属于独立功能迁移 |
| LangGraph / checkpoint / SQLite checkpoint | `1.2.15` / `4.3.0` / `3.1.2` | LangGraph 保持 `>=1.2.15,<1.3.0`，Checkpoint-SQLite 保持 `>=3.1.2,<4.0`；三包共同满足 checkpoint `>=4.3.0`，官方 saver 按 task_path 顺序恢复 DeltaChannel writes，SQLite schema 由 `setup()` 管理 |
| LangGraph Agent Server | API `0.14.6`；runtime `0.34.3`；CLI `0.4.33`；SDK `0.4.7` | API/runtime 按官方协同发布线升级；复核异常重启的 Run 调度、custom FastAPI、auth、stream 和持久化，并完成 [LangGraph Dev 持久化二次开发](langgraph-dev-customizations.md) 的私有接入点与 runtime/checkpoint 精确版本门禁检查；当前未启用 LangSmith API-key auth、encryption、BYOC logging 或 `cancel_on_disconnect` |
| LangSmith Python SDK | `0.14.8` | `>=0.14.8,<0.15.0`，见下方专门说明；满足当前 Deep Agents 的最低依赖 |
| frontend LangChain | Core `1.2.17`；Vue `1.2.4`；LangGraph SDK `1.12.4` | 当前直接消费 `useStream`、Message、content block 和 Tool call projection；SDK 负责 Thread stream 的重连与恢复；queue 使用官方默认 `local` |

## LangSmith 约束说明

`langsmith>=0.14.8,<0.15.0` 是预 1.0 minor 复审边界。项目使用 `Client`、`configure`、`list_projects`、`close` 和标准自动 tracing；multipart 上传重试、404 batch fallback、trace sample rate 元数据和 OTel 导出由 SDK 实现。项目按 Project 路由追踪，不配置 beta Agent addressing、sandbox 或 evaluate。下一次 minor 继续复核 tracing transport、上传与 Client 生命周期。

## 升级方式

LangChain 系升级按调用链分批进行：LangChain/Core 与直接 Provider adapter 可以组成 Python 主干批次；Deep Agents、底层 Provider SDK、frontend message contract、LangSmith tracing 和 Agent Server 分别独立升级。每批使用 scoped `uv lock --upgrade-package <package>` 或 `npm install --save-exact <package>@<version>`，检查 resolver 带入的传递变化后运行最接近的直接测试，并重新生成 `THIRD_PARTY_NOTICES.md`。

上游发布包含新功能、参数或默认行为变化时，先在阶段报告中说明与项目调用面的关系，再决定是否采用；采用后只维护上游现行 contract，不保留旧版本兼容分支。
