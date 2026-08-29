# Agent Shell 领域术语

本页说明 Agent、Workflow 与配置域中的稳定产品术语，不替代管理台全部界面文案。

文档在关系修饰词会影响领域含义或检索结果时，使用可直接检索源码与官方文档的 canonical English term。例如使用 `parent Workflow`、`child Workflow`、`parent Graph`、`Agent subgraph`、`parent Run`、`child Run`、`parent State`、`target Node` 和 `background Run`。每个短章节或短段落应尽早建立所需的 canonical term，后续中文负责解释行为，无需把普通动作、状态和连接词全部翻译成英文。管理台的中文标签保留在【】中，并在第一次出现时附上 canonical term。

| 关系或范围 | canonical term | 使用边界 |
| --- | --- | --- |
| Workflow 角色 | `parent Workflow`、`child Workflow` | 对应 `workflow_role=parent/child` |
| Graph 嵌套 | `parent Graph`、`Agent subgraph` | Workflow StateGraph 调用 Agent subgraph |
| Run 层级 | `parent Run`、`child Run`、`background Run` | Lifecycle 内的运行身份和 detached execution |
| 检查点能力与产物 | `Checkpointer`、`Checkpoint`、`Checkpoint Thread` | Checkpointer 中文为“检查点保存器”，是 Workflow 可选装配组件；Checkpoint 中文为“检查点”，是保存的 State 快照；Checkpoint Thread 只属于启用该组件的 Workflow Run |
| State 投影 | `Workflow State`、`Agent State`、`parent State`、`child State` | `Workflow State` 与 `Agent State` 表示 schema 边界；`parent State` 与 `child State` 只描述实际的状态投影关系 |
| Graph 方向 | `source Node`、`target Node`、`upstream Node`、`downstream Node` | 与 Edge、routing 和 artifact 因果方向一致 |
| Node 类别 | `system Node`、`executable Node`、`Agent Node`、`Command Node` | Start/End 是 system Node；实际执行 callable 的节点是 executable Node |
| Edge 类别 | `Normal Edge`、`Branch Edge`、`Dispatch Edge` | 与 Graph wire handle 和 Catalog contract 对齐 |
| Agent 角色 | `Main Agent`、`Subagent`、`target Agent`、`worker Agent` | `Main Agent` 和 `Subagent` 是产品实体名 |
| 配置与扩展 | `Configuration Repository`、`Model Connection`、`Model Requirement`、`Custom Tool`、`Custom Middleware` | 与 API、catalog type 和源码 owner 对齐 |
| Filesystem 选择 | `Filesystem Backend`、`Filesystem Tools`、`effective Filesystem` | 分别表示后端配置、工具配置，以及继承或替换解析后的最终组合 |
| Graph 发布状态 | `candidate Graph`、`publishable Graph`、`published Graph` | 分别表示待校验文档、满足发布条件的文档，以及已通过 `PUT /graph` 原子保存并令 Workflow `enabled=true` 的文档 |

`source`、`target`、`parent`、`child`、`upstream`、`downstream`、`background` 等容易产生歧义的关系词与领域对象一起写成完整英文短语。同一局部上下文已经建立对应关系后，可以使用自然中文继续说明。界面标签、普通业务说明和不对应代码对象的中文无需翻译。

| 界面名称 | 含义 |
| --- | --- |
| Workflow | 保存 UUID、唯一名称、角色、`enabled`、可选 Workflow Event Output、current Graph document/layout 与运行约束的图实体；只有启用的 parent Workflow 发布到 `/v1/models`，draft 与 child Workflow 不发布 |
| Main Agent | 完整的 Deep Agents assembly，可被 Workflow canvas 中的 Agent Node 引用 |
| Configuration Repository / 配置仓库 | 一套可整体切换的 Component、Agent、Workflow 配置及其 Python/Skill package；写入目标由 active Configuration Repository 决定 |
| 配置库 | 使用通用列表查看和管理配置；系统组也列出实例私有、不可下载的模型连接 |
| 模型连接 | 实例私有的 LangChain Provider、上游地址、具体 model、请求设置和 write-only API Key 配置；不属于 Configuration Repository，也不进入 Bundle |
| 模型要求 | Configuration Repository 中描述所需模型能力的组件，只保存名称和说明 |
| 模型映射 | 按 Configuration Repository 将模型要求绑定到模型连接的页面 |
| Endpoint | Node Catalog 声明的输入/输出控制流端点；支持 Normal Edge、Branch Edge 与 Dispatch Edge |
| Edge | 从 source endpoint 到 target endpoint 的具体激活连接；类型由 Graph contract 定义 |
| Subagent | 具有组件配置名、路由名、说明和 settings，可由 parent Agent 通过 `task` 同步调用的实体 |
| 代理组件 | 可被 Agent 按 UUID 引用的能力配置 |
| 工作流组件 | 被 Workflow metadata 或 canvas Node 引用的固定类型配置 |
| Subagent reference | Main Agent 保存的 `subagent_id`，运行时投影为官方 dictionary-based SubAgent |
| Skill | 含 `SKILL.md` 的按需说明目录 |
| Skill Template / 技能模板 | `data/skills-template/` 中可被选择并复制的 public Skill 素材，以规范相对路径区分同名模板 |
| Skill package / Skill 独立包 | Skill Component 创建后按配置名称保存、由 Component UUID 拥有的独立 Skill 目录；可继续编辑，与原 Template 没有同步关系，并由 CompositeBackend 引用 |
| Custom Tool / 自定义工具 | 从 Python `@tool` 资源物化的 LangChain Tool |
| Custom Middleware / 自定义中间件 | 从本地包加载的官方 LangChain `AgentMiddleware` |
| Command Dispatch | Command 根据 Workflow State/Context 生成动态任务，并由 LangGraph `Send` 分发到 Agent Node |
| Agent Event Output | Main Agent 拥有的 v3 运行事件到响应文本投影规则；Workflow 按稳定 Node/Agent source identity 选择规则 |
| Workflow Lifecycle / 运行历史 | 系统区域 Workflow Lifecycle 下的 Run、结构事件、可选 Checkpoint/Store 摘要与关联诊断；只服务管理端 Debug，不提供 Resume |
