# Agent Shell

Agent Shell 是本地 Workflow 与 Deep Agents 管理台。启用的父图 Workflow 作为 OpenAI-compatible model。

## 开始

Windows 用户请先阅读[启动指南](docs/user-guide/getting-started.md)，然后运行：

```powershell
.\start_server.bat
```

首次运行需确认初始化并设置两次管理密码；启动后访问 `http://127.0.0.1:19100/admin`。管理密码用于 `/admin` 与 `/api/*`，首页另行设置 API Key 后才能调用 `/v1/*`。

完整说明请查看[文档索引](docs/README.md)。

需要由 AI 或自动化程序通过 management API 配置组件、Agent 和 Workflow 时，从 [AI Workflow 编写指南](docs/user-guide/ai-guide/README.md)开始。
