# Agent Shell 文档

这里保存当前版本的公开说明。程序用户从“用户指南”开始，维护者从“开发与版本”开始。

## 程序用户

AI 或自动化程序通过 management API 配置实例时，从 [AI Workflow 编写指南](user-guide/ai-guide/README.md)开始。
索引按任务指向鉴权、对象依赖、Graph、Node 脚本 contract、校验和真实调用；以下页面作为字段与机制下钻。

1. [启动并认识管理台](user-guide/getting-started.md)
2. [创建组件](user-guide/capabilities.md)
3. [管理模型连接与模型映射](user-guide/models.md)
4. [装配 Main Agent 与 Subagent](user-guide/configuration-workflow.md)
5. [理解 Workflow Input Context](user-guide/workflow-input-context.md)
6. [使用自定义 Middleware 包](user-guide/middleware-packages.md)
7. [管理组件库](user-guide/configuration-library.md)
8. [调用 API Server](user-guide/api-server.md)
9. [查看日志中心与运行历史](user-guide/runtime-observability.md)
10. [管理数据、文件与系统设置](user-guide/system-management.md)
11. [安全与部署](security-and-deployment.md)

页面字段索引见[组件说明](wizard-pages/README.md)与 [Agent 说明](agent-pages/README.md)。

## 安装与维护

- [源码运行、Debug 与版本](development-and-release.md)
- [LangChain 系依赖升级](langchain-dependency-upgrades.md)
- [Deep Agents runtime 基线](deep-agents-migration.md)
