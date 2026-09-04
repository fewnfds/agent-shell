# 启动并认识管理台

## 启动

Windows 源码 Clone 需要 Node.js 22；不需要预装 Python，启动器会准备内置 CPython。

Windows 源码 Clone 从项目根运行：

```powershell
.\start_server.bat
```

首次运行若 `data/config/` 不存在，启动器会先询问是否初始化；确认后输入两次管理密码（不含空格的可打印 ASCII，两次不一致会重试）。默认管理台地址是 <http://127.0.0.1:19100/admin>，监听地址、普通端口、LangGraph Dev Run 槽位数和可选 DAP 调试端口可在【系统 / 系统配置】修改。管理台、Management API、OpenAI-compatible API 与 LangGraph Dev 官方 API 共用同一个普通端口；只有显式填写 DAP 调试端口时才增加一个调试 listener。管理台静态壳可以匿名加载，但其数据和操作通过管理密码保护的 `/api/*`；API Key 在【系统 / 系统配置】的网络卡片设置，用于 `/v1/*`。

## 管理台入口

- 【首页】：API Server 状态、访问地址和当前配置提示；
- 【系统】：系统配置、拦截消息、日志中心和运行监控；
- 【文件管理】：浏览和编辑允许开放的真实 `data/...` 目录；
- 【模型】：模型连接编辑器与模型映射；
- 【MCP】：MCP 连接、`mcpServers` JSON 导入与当前 Repository 的 MCP 映射；
- 【代理】：Main Agent 与一层可复用 Subagent；
- 【代理组件】：Main Agent 和 Subagent 使用的能力配置；
- 【工作流】：统一的 Workflow 装配表单和 Vue Flow canvas；
- 【工作流组件】：检查点保存器（Checkpointer）、Workflow Event Output、Response Stream Scheduling 和 Command Node 配置；
- 【配置库】：顶部按全局、工作流、工作流组件、代理和代理组件分组；Repository-owned 配置支持通用列表操作与 Bundle 导入/导出，Model/MCP Connection 仅支持查看、编辑、复制和删除；
- 【词库】：术语查询。

## 第一份可运行 Workflow

首次启动若无可用仓库，会创建并激活 `Default` Configuration Repository；已有仓库时复用并激活现有仓库。需要使用另一套配置时，在【配置库 / 全局 / 组件配置】切换或复制 Repository；之后创建的 Component、Agent 和 Workflow 都写入 current Configuration Repository。

1. 在【代理组件 / 文件系统后端】创建 CompositeBackend 或 LocalShellBackend，并在【代理组件 / 文件系统工具】创建工具配置。需要命令执行时选择真实单工作区的 LocalShellBackend，并在工具配置中开启 `execute`；需要映射、来源权限或 Skill 独立包时选择 CompositeBackend。
2. 在【模型 / 模型连接】创建本机连接，在【代理组件 / 模型要求】创建名称和说明，再在【代理 / Main Agent】中选择模型要求、Filesystem Backend、Filesystem Tools、Agent Event Output 和其他能力；在【代理组件 / Custom Middleware】新建并选择
   `内置示例-agent-additional-prompt`，需要注入 Agent 初始提示词时在 Main Agent 的 `middleware_refs` 中装配。
3. 在【模型 / 模型映射】为 Model Requirement 选择 Model Connection；未绑定时页面显示 warning，必须完成 binding 后才能运行。然后在【工作流】新建记录。需要调整响应流时，在【工作流组件 / 响应流调度】创建配置，再由请求入口 Workflow 装配；未装配时使用内置默认。事件可见性与文本修饰在 Agent/Workflow Event Output 中编写。点击【编辑】进入 Workflow canvas。
   需要 MCP 时，在【代理组件 / MCP 要求】创建 portable Requirement，在【MCP / MCP 连接】创建或导入实例 Connection，在【MCP / MCP 映射】完成 binding，最后由 Main Agent、Subagent 或 Command 的 MCP Card 选择 Requirement 与 Tool 范围。
4. 添加 Agent Node，选择 Main Agent，连接 `Start -> Agent -> End` 后点击【保存草稿】（草稿保持 disabled）。
5. 点击【正式保存 Workflow】通过校验后启用 Workflow；全部 enabled Workflow 都会出现在 `/v1/models`，也可以被其他 Run 调用。
6. 在【系统 / 系统配置】设置 API Key，通过全局 navbar 的 API Server 控件启动服务；调用 `/v1/models` 时携带 `Authorization: Bearer <API Key>`，确认 Workflow 名称后以
   `{"model":"<workflow-name>","messages":[...]}` 调用 `/v1/chat/completions`。
