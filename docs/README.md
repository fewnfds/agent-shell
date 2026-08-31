# Agent Shell 文档

这里保存当前 dev 滚动源码对应的公开说明。程序用户从[用户指南总览](user-guide/README.md)开始，维护者从“开发与版本”开始；非公开工程契约和陷阱位于仓库内 `.docs/`。

## 程序用户

人类用户从[用户指南总览](user-guide/README.md)开始，AI 或自动化程序通过 management API 配置实例时，从 [AI Workflow 编写指南](user-guide/ai-guide/README.md)开始。
索引按任务指向鉴权、对象依赖、Graph、Node 脚本 contract、校验和真实调用；以下页面作为字段与机制下钻。

1. [启动并认识管理台](user-guide/getting-started.md)
2. [创建组件](user-guide/capabilities.md)
3. [管理模型连接与模型映射](user-guide/models.md)
4. [管理 MCP 连接、映射与调用](user-guide/mcp.md)
5. [装配 Main Agent 与 Subagent](user-guide/configuration-workflow.md)
6. [使用 Agent Additional Prompt](user-guide/agent-additional-prompt.md)
7. [使用 Custom Middleware 包](user-guide/middleware-packages.md)
8. [管理配置库](user-guide/configuration-library.md)
9. [调用 API Server](user-guide/api-server.md)
10. [查看日志中心与运行历史](user-guide/runtime-observability.md)
11. [管理数据、文件与系统设置](user-guide/system-management.md)
12. [安全与部署](security-and-deployment.md)

组件与 Agent 的逐字段契约见 [组件说明](wizard-pages/README.md) 与 [Agent 配置](agent-pages/README.md)。

## 维护与基线

- [源码运行、Debug 与版本](development-and-release.md)
- [LangChain 系依赖升级](langchain-dependency-upgrades.md)
- [Deep Agents runtime 基线](deep-agents-migration.md)

当前运行时与依赖基线以 [源码运行、Debug 与版本](development-and-release.md) 和 `server/pyproject.toml` 为准。
