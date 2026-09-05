# Agent Shell server

`server/` 是 Agent Shell 的 FastAPI 后端和 Deep Agents runtime。可编辑前端源码位于根目录
`frontend/`，production 前端产物由后端托管。

主要接口（精选入口；完整注册表以 `server/src/agent_shell/app.py:create_app()` 和各 `api/` router 为准）：

- `/admin`：管理台；
- `/api/health`、`/api/readiness`：存活与就绪状态；
- `/api/catalog`、`/api/blocks/{type}`：组件目录与 CRUD；
- `/api/main-agents`、`/api/subagents`：Agent 配置；
- `/api/blocks/{type}`、`/api/skills`：用户组件和 Skill 资源发现；
- `/api/workflows`、`/api/workflow-node-catalog`：Workflow、Graph 草稿/校验/正式保存；
- `/api/configuration-repositories/*`、`/api/configuration-bundles/*`：Repository 管理与 Bundle 导出/预检/导入；
- `/api/model-connections`、`/api/model-requirements/{id}/binding`：模型连接与当前 Repository 的模型绑定；
- `/api/file-manager`、`/api/system/settings`：数据与实例设置；文件管理只接受规范 `data/...` 路径；
- `/api/message-interception`：管理入站拦截的内存 sequence/latest；启用时 `/v1/chat/completions` 返回固定拦截占位；
- `/api/event-feed`、`/api/runtime-diagnostics`、`/api/workflow-lifecycles`：系统日志、请求级诊断、Lifecycle catalog、监控设置与运行监控读取；
- `/v1/models`、`/v1/chat/completions`：OpenAI-compatible 推理接口。

公开推理入口只接受 `enabled=true` 且 `is_model_entry=true` 的 Workflow name；任何已启用 Workflow 仍能通过 Workflow Runtime Context 被其他 Run 调用。每个推理请求从一次不可变配置快照解析 Workflow，再通过 `deepagents.create_deep_agent()` 构造 Main Agent 和同步 Subagent；配置期已做静态校验，请求期按当前 Workflow 可达集从快照物化用户资源。客户端每次提交完整 `messages[]`，系统不跨请求累积产品聊天历史。
LangGraph Dev 是 Assistant、Thread、Run、checkpoint、State/history 和 Store 的执行事实 owner。Workflow Lifecycle 只按一次客户端请求聚合全部 Run；management monitoring GET 通过公共 API 读取官方 Run、Assistant Graph、latest Thread State 和 State history。当前没有 Resume、time travel、推送监控或运行归档入口。

## 运行与开发

普通源码运行从仓库根执行：

```powershell
.\start_server.bat
```

新实例默认监听 `127.0.0.1:19100`。应用 runtime diagnostic 索引位于 `data/state/agent-shell.sqlite3`；LangGraph Dev 的 Assistant、Thread、Run、checkpoint、State/history 和 Store 数据集中位于 `data/state/langgraph-dev/.langgraph_api/`。直接运行模块时 `--home <appHome>` 为必填，`--data-dir <dataRoot>` 可选且相对路径按 `--home` 解析，`--port <PORT>` 可覆盖监听端口；`start_server.bat` 会自动推导 `--home` 和默认 data root。

后端开发（主测试集位于仓库根 `test/`）：

```powershell
cd server
.\.venv\Scripts\python.exe -m pytest ..\test\<domain>\test_relevant_module.py -q
```

`.venv` 首次准备必须显式使用项目自带的 uv 与 CPython，避免 PATH 上其他软件的 uv 选择用户目录解释器。完整首建命令见[开发与发布](../docs/development-and-release.md#验证)，日常不要使用裸 `python`、`pip` 或 `uv run pytest`。
测试启动时会校验 `agent_shell` 实际来自当前仓库；系统 Python 的用户级 editable package 不会被静默接受。
其余说明见根 [README](../README.md) 和 [用户指南](../docs/user-guide/README.md)。
