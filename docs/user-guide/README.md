# Agent Shell 用户指南

Agent Shell 通过管理台组合 Workflow、Main Agent/Subagent 与 Component configuration（基于 Deep Agents runtime），并把 enabled parent Workflow 暴露为 OpenAI-compatible model。

[AI Workflow 编写指南](ai-guide/README.md)是 AI 或自动化程序的索引，下面的详细页面按任务领域展开。

推荐顺序：

1. [启动并认识管理台](getting-started.md)
2. [创建组件（代理组件与工作流组件）](capabilities.md)
3. [管理模型连接与模型映射](models.md)
4. [装配 Workflow、Main Agent 与 Subagent](configuration-workflow.md)
5. [使用 Agent Additional Prompt](agent-additional-prompt.md)
6. [使用文件化 Python 扩展（Custom Middleware / Command / Task Dispatcher）](middleware-packages.md)
7. [管理配置库](configuration-library.md)
8. [调用 API Server](api-server.md)
9. [查看日志中心与运行历史](runtime-observability.md)
10. [管理数据、文件与系统设置](system-management.md)

三个基础边界是：

- Main Agent 必选且仅需模型要求与 Agent Event Output；Subagent 仅模型要求必选；
- 客户端在每次请求中提交完整消息；
- `data/` 是需要备份和迁移的完整实例数据根，`runtime/` 可重建，不进入备份，外部 mapped path 需另行迁移。

模型连接与映射的使用方式见 [管理模型连接与模型映射](models.md)。字段级索引见 [组件说明](../wizard-pages/README.md) 与 [Agent 配置](../agent-pages/README.md)；鉴权与部署见 [安全与部署](../security-and-deployment.md)；完整公开索引见 [Agent Shell 文档](../README.md)。
