# Agent Shell 用户指南

Agent Shell 通过管理台组合 Deep Agents 配置，并把启用的父图 Workflow 暴露为 OpenAI-compatible model。

[AI Workflow 编写指南](ai-guide/README.md)是 AI 或自动化程序的索引，下面的详细页面按任务领域展开。

推荐顺序：

1. [启动并认识管理台](getting-started.md)
2. [创建组件](capabilities.md)
3. [管理模型连接与模型映射](models.md)
4. [装配 Main Agent 与 Subagent](configuration-workflow.md)
5. [理解 Workflow Input Context](workflow-input-context.md)
6. [使用自定义 Middleware 包](middleware-packages.md)
7. [管理组件库](configuration-library.md)
8. [调用 API Server](api-server.md)
9. [查看日志中心与运行历史](runtime-observability.md)
10. [管理数据、文件与系统设置](system-management.md)

三个基础边界是：Main Agent 的必选组件包括模型要求和 Agent 事件输出；客户端在每次请求中提交完整消息；
`data/` 是需要备份和迁移的完整实例数据根。
模型连接与映射的使用方式见 [模型](models.md)。
