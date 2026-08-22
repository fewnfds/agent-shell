# 启动并认识管理台

## 启动

Windows 源码 Clone 从项目根运行：

```powershell
.\start_server.bat
```

首次启动输入两次管理密码。默认管理台地址是 <http://127.0.0.1:19100/admin>。管理密码用于 `/admin` 与
`/api/*`；首页的 API Key 用于 `/v1/*`。

## 管理台入口

- 【首页】：API Server 状态、访问地址和当前配置提示；
- 【系统】：系统配置、拦截消息、日志中心和运行历史；
- 【文件管理】：浏览和编辑允许开放的真实 `data/...` 目录；
- 【模型】：模型连接编辑器与模型映射；
- 【代理】：Main Agent 与一层可复用 Subagent；
- 【代理组件】：Main Agent 和 Subagent 使用的能力配置；
- 【工作流】：父图与子图的装配表单和 Vue Flow 画布；
- 【工作流组件】：Workflow 事件输出、Command 和任务分发配置；
- 【配置库】：顶部按全局、工作流、工作流组件、代理和代理组件分组；全局组包含组件配置和模型连接，并通过通用列表查看、复制、编辑、下载、上传和删除配置；
- 【词库】与【样式基准】：术语查询和 UI 样式基准核对。

## 第一份可运行 Workflow

首次启动会创建并激活 `Default` Configuration Repository。需要使用另一套配置时，在【配置库 / 全局 / 组件配置】切换或复制 Repository；之后创建的 Component、Agent 和 Workflow 都写入当前 Repository。

1. 在【代理组件 / 文件系统】创建共享空间配置。
2. 在【模型 / 模型连接】创建本机连接，在【代理组件 / 模型要求】创建名称和说明，再在【代理 / Main Agent】中选择模型要求、
   Agent 事件输出和其他能力；需要把客户端多轮消息整理到 Agent 初始上下文时，从
   `内置示例-workflow-input-context` 创建 Custom Middleware 并装配到 Agent。
3. 在【模型 / 模型映射】为模型要求选择模型连接，在【工作流 / 父图】新建记录；点击【编辑 Flow】进入全屏画布。
4. 添加 Agent 节点，选择 Main Agent，连接 `Start -> Agent -> End` 并保存。
5. 启用 Workflow，在首页设置 API Key 并启动 API Server。
6. 调用 `/v1/models` 确认名称，再使用该名称调用 `/v1/chat/completions`。
