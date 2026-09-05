# 管理配置库

## 列表与 Repository 切换

【配置库】的【组件配置】（Configuration Repository）与 Component、Agent、Workflow 分类复用通用表格，但 Repository 列表和组件配置列表是两个独立页面；顶部固定为全局、工作流、工作流组件、代理和代理组件五组。全局组还包含【模型连接】与【MCP 连接】；Component、Agent 和 Workflow 支持搜索、查看、编辑、复制、下载、删除，已应用筛选且命中记录后才可批量删除，两类实例 Connection 支持查看、编辑、复制和删除，不提供 Bundle 下载或批量删除。

普通列表只读取 summary 和当前页，打开详情或编辑时再读取该记录的完整配置；筛选与分页由 Management API 返回 `total` 和当前 Repository revision。配置修改、Bundle、Repository 切换和运行快照仍由后端在需要时读取完整 Repository，这些原子边界不依赖浏览器持有整仓数据。

Configuration Repository 的列表和切换入口位于【配置库 / 全局 / 组件配置】。该表格显示 active 状态，并提供切换、复制、下载和删除；当前 active Repository 不能删除。Repository 副本使用全新配置 UUID，重写声明式引用并复制私有 Python/Skill package；Workflow 副本固定为 disabled。Model/MCP Connection 与 secret 不随 Repository 复制或下载，repository-scoped Model/MCP Mapping 会按新 Requirement UUID 复制。

系统设置、secret、SQLite/LangGraph Dev 运行数据、日志、媒体、普通文件、Python Template、Skill Template、模型连接和 MCP 连接属于实例域，切换 Repository 时保持不变。模型与 MCP 映射存储也属于实例域，其中的 binding 按 Repository UUID 分区；切换后页面使用所选 Repository 自己的 binding。请求开始装配时会捕获所用 Repository 的配置、模型与 MCP 资源视图，后续切换只影响新请求。

- 编辑会跳转到对应页面，并以记录 UUID 确定更新目标；
- 复制会创建新 UUID，副本名称经过当前校验；Python private package 与 Skill package 按配置名称目录一起复制，manifest owner 改为新 UUID；
- 配置 UUID 是全部 Repository 间全局唯一的小写 UUID4；Component、Main Agent、Subagent、Workflow 之间也不能复用同一 UUID；
- Component 按 type、Main Agent 按 `name`、Subagent 按 `component_name` 在各自作用域内保持大小写不敏感唯一；Workflow name 保留大小写与空格敏感的精确唯一语义，并在 Workflow 同时启用且选择作为模型入口时作为公开 model ID；
- 详情显示保存的完整 payload，包括当前版本无法识别或无法运行的记录；
- Component、Main Agent、Subagent 和 Workflow 都可以独立删除；删除目标只清理该记录及其自有 Python/Skill package，不会自动修改其他配置；
- 引用方保留已删除目标的 UUID，Repository 校验会产生 `configuration.reference_not_found`；UUID 存在但 target type 错误时产生 `configuration.reference_type_mismatch`；
- 首页和配置库显示 active Repository 的全部问题；Component、Main Agent、Subagent 和 Workflow 编辑页只显示当前 owner 的问题；
- 引用选择器会显示“配置已缺失”和原 UUID。用户可以改选现存配置，或在该字段允许时移除引用；页面加载与 catalog 刷新不会改写 payload；
- 单项与批量删除使用同一语义，每条记录保存为独立 YAML 文件。Active Repository 仍不能删除；Model/MCP Connection 和 repository-scoped binding 仍由各自的实例级资源 owner 管理。

## 校验与存储位置

Repository 校验同时检查组件、Main Agent、Subagent 和 Workflow；Workflow 草稿中的缺失引用、UUID 指向错误类型以及 Graph admission 问题也会显示。满足磁盘身份格式但业务配置无效的记录仍可查看、编辑、整库复制、下载和切换；整库复制会重写仍存在的 target UUID，已悬空 UUID 保持不变并在副本中继续报警。Agent 装配、Workflow publish 和运行会重新校验并拒绝不完整引用；
文件名、文档 ID、`kind`、`type` 或 `schema_version` 错位属于无法可靠识别 owner 的存储损坏，服务会在加载时拒绝。
Component、Main Agent、Subagent 和 Workflow YAML 分别位于 `data/config_repos/<repository-name>/components/<type>/<uuid>.yaml`、`agents/main/<uuid>.yaml`、`agents/subagent/<uuid>.yaml` 和 `workflows/<uuid>.yaml`；Python private package 与 Skill package 位于同一 Repository 的 `python_packages/` 与 `skill_packages/`。`data/config/` 保存实例私有 Model/MCP Connection、repository-scoped Model/MCP binding、系统配置、secret env 和 active Repository pointer，这些不属于可迁移配置。`data/state/agent-shell.sqlite3` 保存 runtime diagnostic 索引；LangGraph Dev 在 `data/state/langgraph-dev/.langgraph_api/` 拥有 Assistant、Thread、Run、checkpoint、State/history 和 Server Store 运行数据。

## 原子配置 Bundle API

current backend 可以把一个 Component、Subagent、Main Agent 或 Workflow 作为 single-root export。Bundle 是 ZIP，root record 所需的声明式配置依赖会自动闭合；shared dependency 只保存一次。single-root closure 中存在缺失或类型错误的引用时，export 返回 `configuration_bundle_invalid`，不生成不完整 Bundle。整仓库下载是另一种原样诊断快照，会保留悬空 UUID。Management API 为：

- `POST /agent-shell/api/configuration-bundles/export`：JSON body 使用 `kind`、`source_id`，Component 根另带 `type`；返回 Bundle ZIP。下载名只保留 ASCII 字母数字、`-`、`_` 和 `.`，其他字符替换为 `-`，再去除首尾的 `-`/`.`；空名回退到 root kind，Windows 保留设备名增加 `configuration-` 前缀，并使用 `.agent-shell-config.zip` 后缀；实际文件名以响应的 `Content-Disposition` 为准。整仓库下载是另一种 `agent-shell.configuration-repository` 格式，使用 `.agent-shell-repository.zip` 后缀。
- `POST /agent-shell/api/configuration-bundles/preview`：multipart 的 `bundle` 文件；返回 `bundle_sha256`、固定 target UUID map、名称建议、Filesystem binding、errors、warnings 和本次 preview 的 `plan_token`；
- `POST /agent-shell/api/configuration-bundles/import`：再次提交同一个 multipart `bundle`，并在 `request` form field 中提交 JSON；JSON 包含 preview 的 `bundle_sha256`、`plan_token`，以及与源记录一一对应的 `resolutions.target_ids`、可选 `resolutions.names` 和 `resolutions.filesystem_bindings`。

配置库根据当前名称输入、服务端 blocker 和 Filesystem binding 实时决定是否允许导入；mapped directory 还需明确 path origin。名称冲突时服务端建议的新名称只作为提示，不会被当成用户已确认值；输入有效新名称后可提交，commit 仍由服务端按当前 active Repository 再次校验。commit 复用本次 preview 的 `bundle_sha256`、`plan_token` 和 target UUID map。导入成功后刷新当前列表并留在原页面。

导入不会按源 UUID 或名称复用、更新或覆盖配置。每条配置使用 preview 给出的新 UUID，声明式引用由后端机械重写；
名称冲突会建议 `Name (imported)`、`Name (imported 2)` 等后缀，冲突名称必须显式确认。Workflow 导入后固定为 `enabled=false`，需检查路径、credential、Skill、Python code 和依赖后再验证并启用。

单根 Bundle 的 manifest 固定保存 `format`、`format_version`、`source_application_version`、`root`、`records` 和 `assets`；`root` 保存 `kind`、`source_id`，Component 根另存 `type`。Workflow `role` 由 root record payload 投影到 preview。preview 会核对 root 与记录身份、依赖闭包、hash 和资源 owner。导入目标类型由已校验 manifest 决定，Filesystem Bundle 按其 manifest 恢复为 Filesystem。【配置库 / 全局 / 组件配置】的下载使用独立的 `agent-shell.configuration-repository` 整仓库格式。

未知或不受信任的配置可能包含以 Agent Shell 权限运行的 Python/Skill 代码、文件系统访问、网络访问或欺骗性引用。导入或分享前必须检查来源、提示词、Skill 文件、Python 源码、requirements、文件系统绑定与权限。preview 的 warning 使用稳定 `message_key/message_args` 本地化显示，不直接把后端英文作为普通界面文案。

Python-backed Component 会携带完整 owner package，并在目标实例用目标配置名称建立 folder、用新 UUID 写入 `package.json.id`；导入过程只做静态扫描，不 import factory。Skill Component 携带完整 Skill package，并在目标实例用目标配置名称建立目录，不做全局 Skill 名称复用或冲突判断。

Filesystem 的 absolute mapped directory、virtual directory `source_path` 和 virtual file `source_path` 必须在目标实例显式重绑；mapped directory 还必须选择 `absolute` 或 `data-root-relative` path origin。data-root-relative mapped directory 可以保留源相对路径，它必须没有 drive、root、冒号和 `.`/`..` 段；合法目标不存在时 preview 只给出不阻塞提交的 warning。损坏 ZIP、manifest、hash、entry path 或请求格式返回 422；digest、preview plan、名称或目标实例状态冲突返回 409。
