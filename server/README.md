# Agent Shell server

`server/` 是 Agent Shell 的 FastAPI 后端和 Deep Agents runtime。可编辑前端源码位于根目录
`frontend/`，production 前端产物由后端托管。

主要接口：

- `/admin`：管理台；
- `/api/health`、`/api/readiness`：存活与就绪状态；
- `/api/catalog`、`/api/blocks/*`：组件目录与 CRUD；
- `/api/main-agents`、`/api/subagents`：Agent 配置；
- `/api/blocks/custom-tool`、`/api/blocks/custom-middleware`、`/api/skills`：用户资源发现；
- `/api/file-manager/*`、`/api/system/settings`：数据与实例设置；
- `/api/message-interception`：管理入站消息拦截并读取进程内最新请求；
- `/api/event-feed`：系统日志与请求级运行错误诊断；
- `/v1/models`、`/v1/chat/completions`：OpenAI-compatible 推理接口。

每个推理请求从一次不可变配置快照解析当前 Workflow，再通过 `deepagents.create_deep_agent()` 构造 Main Agent 和
同步 Subagent。用户资源文件在装配时重新校验和物化。客户端每次提交完整 `messages[]`，系统不跨请求累积产品聊天历史。
Workflow Lifecycle 保存 Run/Event 结构历史并使用官方 checkpoint，但这些数据只服务管理端 Debug；当前没有 Resume 执行入口。

## 运行与开发

普通源码运行从仓库根执行：

```powershell
.\start_server.bat
```

新实例默认监听 `127.0.0.1:19100`，数据库默认位于
`data/state/agent-shell.sqlite3`。启动参数 `--home` 与 `--data-dir` 可分别指定应用目录和数据目录。

后端开发：

```powershell
cd server
.\.venv\Scripts\python.exe -m pytest ..\test\<domain>\test_relevant_module.py -q
```

`.venv` 首次准备必须显式使用项目自带的 uv 与 CPython，避免 PATH 上其他软件的 uv 选择用户目录解释器。
测试启动时会校验 `agent_shell` 实际来自当前仓库；系统 Python 的用户级 editable package 不会被静默接受。
完整命令见[开发与发布](../docs/development-and-release.md)。其余说明见根 [README](../README.md)和
[用户指南](../docs/user-guide/README.md)。
