# Agent Shell

Agent Shell 是本地 Workflow 与 Deep Agents 管理台。启用的父图 Workflow 作为 OpenAI-compatible model；模型连接在【模型 / 模型连接】维护，模型要求由 Main Agent/Subagent 必选引用，并在【模型 / 模型映射】绑定到具体连接。每个 Workflow 保存一份当前 Vue Flow 图；运行时共享 Filesystem 由 Agent 的 Filesystem capability 提供，不嵌入 Workflow。
画布支持 Start、Agent、Command、任务分发（Task Dispatcher）和 End 节点；后台 Run 管理通过项目私有 `WorkflowRuntimeContext.background_runs` facade 提供，不占用画布 Node。Agent 节点引用完整 Main Agent 装配，并可通过官方 `SubAgentMiddleware` 同步委派 Subagent。

管理台将代理组件与工作流组件分开管理。Workflow 组件按 Catalog 固定类型（Command、Task Dispatcher、Workflow Event Output 等）分别提供配置、校验、画布和运行时闭环；Command 组件的 Python 逻辑读取完整 Workflow State/Runtime Context，返回 Agent Shell 的 `{update, activate}` contract，编译期再映射为 LangGraph `Command` 以更新 State 并激活分支。

## 开始

Windows 用户请先阅读[启动指南](docs/user-guide/getting-started.md)，然后运行：

```powershell
.\start_server.bat
```

首次运行需确认初始化并设置两次管理密码；启动后访问 `http://127.0.0.1:19100/admin`。管理密码用于 `/admin` 与 `/api/*`，首页另行设置 API Key 后才能调用 `/v1/*`。

完整说明请查看[文档索引](docs/README.md)。

需要由 AI 或自动化程序通过 management API 配置组件、Agent 和 Workflow 时，从 [AI Workflow 编写指南](docs/user-guide/ai-guide/README.md)开始，不要根据 OpenAPI 中的通用 JSON body 猜字段。仓库是源码分发；`data/` 是实例持久数据，`runtime/` 是可重建产物。
