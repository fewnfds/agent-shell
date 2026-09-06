# Agent Shell

Agent Shell Workflow 与 Deep Agents 管理台。`is_model_entry=true`的Main Agent，以及已正式保存且选择作为模型入口的Workflow可作为OpenAI-compatible model。

## 开始

Windows 用户请先阅读[启动指南](docs/user-guide/getting-started.md)，然后运行：

```powershell
.\start_server.bat
```

首次运行需确认初始化并设置管理密码。管理密码用于 `/admin` 与 `/api/*`，另行设置 API Key 后才能调用 `/v1/*`。

完整说明请查看[文档索引](docs/README.md)。

需要由 AI 或自动化程序通过 management API 配置时，从 [AI Workflow 编写指南](docs/user-guide/ai-guide/README.md)开始。
