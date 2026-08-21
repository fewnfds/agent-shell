# Agent Shell

Agent Shell 是本地 Workflow 与 Deep Agents 管理台。启用的父图 Workflow 作为 OpenAI-compatible model；模型连接在模型页面维护，
模型要求由代理组件引用并通过模型映射绑定；每个 Workflow
保存一份当前 Vue Flow 图和共享 Filesystem。画布支持 Start、Agent、Command、任务分发和 End 节点；后台 Run 管理通过
官方 Runtime Context 的窄命令 facade 提供，不占用画布 Node。Agent 节点引用完整
Main Agent 装配，并可通过官方 `SubAgentMiddleware` 同步委派 Subagent。

管理台将代理组件与工作流组件分开管理。Workflow 组件按受限类型逐个提供配置、校验、画布和运行时闭环；
当前 Command 组件使用 Python 逻辑读取完整 Workflow State/Runtime Context，并通过 LangGraph `Command` 更新 State、激活零个、一个或多个具名分支。

## 开始

Windows 用户请先阅读[启动指南](docs/user-guide/getting-started.md)，然后运行：

```powershell
.\start_server.bat
```

完整说明请查看[文档索引](docs/README.md)。

需要由 AI 或自动化程序通过 management API 配置组件、Agent 和 Workflow 时，从
[AI Workflow 编写指南](docs/user-guide/ai-guide/README.md)开始，不要根据 OpenAPI 中的通用 JSON body 猜字段。
