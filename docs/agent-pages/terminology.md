# 词库

| 界面名称 | 含义 |
| --- | --- |
| Workflow | 保存当前 Graph definition/layout 与运行约束的图实体；父图可映射 `/v1/models`，子图只作为内部目标 |
| Main Agent | 完整的 Deep Agents 装配，可被 Workflow 画布的 Agent node 引用 |
| Configuration Repository / 配置仓库 | 一套可整体切换的 Component、Agent、Workflow 配置及其私有包；写入目标由当前 active Repository 决定 |
| 配置库 | 使用通用列表查看和管理配置；系统组也列出实例私有、不可下载的模型连接 |
| 模型连接 | 实例私有的 LangChain Provider、上游地址、具体 model、请求设置和 API Key 配置 |
| 模型要求 | Configuration Repository 中描述所需模型能力的组件，只保存名称和说明 |
| 模型映射 | 按 Configuration Repository 将模型要求绑定到模型连接的页面 |
| Endpoint | Node Catalog 声明的输入/输出控制流端点；当前 Edge 类型为 normal、branch、dispatch |
| Edge | 从 source endpoint 到 target endpoint 的具体激活连接；不是 Vue Flow renderer 类型 |
| Subagent | 具有组件配置名、路由名、说明和 settings，可由父 Agent 通过 `task` 同步调用的实体 |
| 代理组件 | 可被 Agent 按 UUID 引用的能力配置 |
| 工作流组件 | 被 Workflow metadata 或画布 Node 引用的固定类型配置 |
| Subagent 引用 | Main Agent 保存的 `subagent_id`，运行时投影为官方字典 SubAgent |
| Skill | 含 `SKILL.md` 的按需说明目录 |
| Skill Template / 技能模板 | `data/skills-template/` 中可被选择并复制的公共 Skill 素材，以规范相对路径区分同名模板 |
| 私有 Skill package | Skill Component 创建后按 owner UUID 保存的独立 Skill 目录；可继续编辑，与原 Template 没有同步关系 |
| 自定义工具 | 从 Python `@tool` 资源物化的 LangChain Tool |
| 自定义 Middleware | 从本地包加载的官方 LangChain `AgentMiddleware` |
| Task Dispatcher | 从 Workflow State/Context 生成动态任务，并由 LangGraph `Send` 分发到 Agent Node 的画布节点 |
| Agent 事件输出 | Main Agent 拥有的 v3 运行事件到响应文本投影规则；Workflow 按稳定 node/Agent 来源选择规则 |
| Workflow 执行历史 | 系统区域 Workflow Lifecycle 下的 Run、结构事件、checkpoint/Store 摘要与关联诊断；只服务管理端 Debug，不提供 Resume |
