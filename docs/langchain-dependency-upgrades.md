# LangChain 系依赖升级

本文记录 LangChain 系依赖的当前维护边界。精确版本以 `server/pyproject.toml`、`server/uv.lock`、`frontend/package.json` 和 `frontend/package-lock.json` 为准。

## 当前基线

| 依赖 | 当前版本 | 约束策略 |
| --- | ---: | --- |
| Deep Agents | `0.7.13` | 精确锁定；项目依赖其 middleware 顺序、Filesystem、Subagent 和 trace policy 行为；fork mode 未启用 |
| LangChain / Python Core | `1.4.0` / `1.6.2` | 保持当前 major；`langchain.mcp` 是尚未启用的 beta 能力，现有 MCP 继续由 adapters 提供 |
| Anthropic / OpenAI | `1.7.1` / `1.6.1` | 按 Provider 分组升级并复核 model profile、content block 和错误边界 |
| Google GenAI / Vertex AI | `4.4.0` / `3.2.4` | 各自保持当前 major；Google GenAI 当前配套底层 `google-genai 2.22.0` |
| DeepSeek / xAI | `1.1.0` / `1.3.0` | 各自保持当前 major，并与 OpenAI-compatible 路径一起回归 |
| MCP adapters | `0.3.2` | 当前使用 `MultiServerMCPClient`；新的 beta `langchain.mcp` 属于独立功能迁移 |
| LangGraph / SQLite checkpoint | `1.2.11` / `3.1.1` | LangGraph 保持 `<1.3.0`，Checkpoint-SQLite 保持 `<4.0` |
| LangGraph Agent Server | API `0.14.0`；runtime `0.34.0`；CLI `0.4.31`；SDK `0.4.4` | API/runtime 按官方协同发布线升级；当前未启用 LangSmith API-key auth、encryption、BYOC logging 或 `cancel_on_disconnect` |
| LangSmith Python SDK | `0.12.2` | `>=0.12.2,<0.13`，见下方专门说明 |
| frontend LangChain | Core `1.2.9`；Vue `1.0.35`；LangGraph SDK `1.10.2` | 当前直接消费 `useStream`、Message、content block 和 Tool call projection |

## LangSmith 约束说明

`langsmith>=0.12.2,<0.13` 是预 1.0 minor 复审边界。项目使用 `Client`、`configure`、`list_projects`、`close` 和标准自动 tracing；当前接受确定性 trace sampling、anonymization fail-closed、`httpx2` 优先 transport，以及上传 `429/500` 重试语义。下一次 minor 继续单独复核 tracing transport、上传与 Client 生命周期。

## 升级方式

LangChain 系升级按调用链分批进行：LangChain/Core 与直接 Provider adapter 可以组成 Python 主干批次；Deep Agents、底层 Provider SDK、frontend message contract、LangSmith tracing 和 Agent Server 分别独立升级。每批使用 scoped `uv lock --upgrade-package <package>` 或 `npm install --save-exact <package>@<version>`，检查 resolver 带入的传递变化后运行最接近的直接测试，并重新生成 `THIRD_PARTY_NOTICES.md`。

上游发布包含新功能、参数或默认行为变化时，先在阶段报告中说明与项目调用面的关系，再决定是否采用；采用后只维护上游现行 contract，不保留旧版本兼容分支。
