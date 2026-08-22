# 管理配置库

【配置库】使用同一个通用列表，顶部固定为全局、工作流、工作流组件、代理和代理组件五组。全局组包含【组件配置】（Configuration Repository）和【模型连接】；Component、Agent 和 Workflow 支持搜索、查看、编辑、复制、下载、删除和筛选后批量删除，模型连接支持查看、编辑、复制和删除，不提供上传、下载或批量删除。

Configuration Repository 的列表和切换入口位于【配置库 / 全局 / 组件配置】。该表格显示 active 状态，并提供切换、复制、下载和删除；当前 active Repository 不能删除。Repository 副本使用全新配置 UUID，重写声明式引用并复制私有 Python/Skill package；Workflow 副本固定为 disabled。模型连接与 credential 不随 Repository 复制或下载，repository-scoped 模型映射会按新 Model Requirement UUID 复制。

系统设置、secret、SQLite/运行历史、日志、媒体、普通文件、Python Template、Skill Template 和模型连接属于实例域，切换 Repository 时保持不变。模型映射存储也属于实例域，其中的 binding 按 Repository UUID 分区；切换后页面使用所选 Repository 自己的 binding。请求开始装配时会捕获所用 Repository 的配置和模型资源视图，后续切换只影响新请求。

- 编辑会跳转到对应页面，并以记录 UUID 确定更新目标；
- 复制会创建新 UUID，副本名称经过当前校验；Python package 与 Skill private package 随 owner UUID 一起复制；
- 配置 UUID 是全局唯一的小写 UUID4；组件、Main Agent、Subagent、Workflow 之间也不能复用同一 UUID；
- Component 按 type、Main Agent 和 Subagent 的组件名分别在作用域内按大小写不敏感的名称唯一；Workflow name 保留大小写敏感的精确唯一语义，并继续作为公开 model ID；
- 详情显示保存的完整 payload，包括当前版本无法识别或无法运行的记录；
- 删除可选组件或 Subagent 实体时，服务端会在一次配置更新中从所有 Agent 配置摘除对应引用；
- Main Agent 必选的模型要求和 Agent 事件输出在仍被引用时删除会返回冲突，替代配置解除引用后即可删除；
- Main Agent 被任一 Workflow Graph 的 Agent Node 引用时，单项或批量删除都会返回冲突；批量删除不会先删除其中未引用的记录；
- 批量删除与引用摘除由文件配置仓库统一写入；每条记录保存为独立 YAML 文件；
- catalog 中无法装配的组件类型会显示为失效引用，可在 Agent 编辑页移除；删除该记录时服务端也会自动摘除引用。

Repository 校验同时检查组件、Main Agent、Subagent 和 Workflow；Workflow 草稿中的缺失引用、UUID 指向错误类型以及
Graph admission 问题也会显示。满足磁盘身份格式但业务配置无效的记录仍可查看和编辑，复制与运行会重新校验；
文件名、文档 ID、`kind`、`type` 或 `schema_version` 错位属于无法可靠识别 owner 的存储损坏，服务会在加载时拒绝。
组件、Agent 和 Workflow YAML 以及 Python/Skill private package 保存在 `data/configuration-repositories/<repository-uuid>/`；`data/config/` 还保存实例私有 Model Connection 与 repository-scoped model binding，但这些不属于可迁移配置；其余内容为系统配置、secret env 和 active repository pointer。SQLite 只保存运行记录、checkpoint、诊断和媒体元数据。

## 原子配置 Bundle API

当前后端可以把一个 Component、Subagent、Main Agent 或 Workflow 作为单根导出。Bundle 是 ZIP，根记录所需的
声明式配置依赖会自动闭合；共享依赖只保存一次。管理 API 为：

- `POST /api/configuration-bundles/export`：JSON body 使用 `kind`、`source_id`，Component 根另带 `type`；返回 ZIP。下载名只保留 ASCII 字母数字、`-`、`_` 和 `.`，其他字符替换为 `-`，Windows 保留设备名增加 `configuration-` 前缀，并统一使用 `.agent-shell-config.zip` 后缀；实际文件名以响应的 `Content-Disposition` 为准；
- `POST /api/configuration-bundles/preview`：multipart 的 `bundle` 文件；返回 `bundle_sha256`、固定 target UUID map、名称建议、
  Filesystem binding、errors、warnings 和本次 preview 的 `plan_token`；
- `POST /api/configuration-bundles/import`：再次提交同一个 multipart `bundle`，并在 `request` form field 中提交 JSON；JSON 包含
  preview 的 `bundle_sha256`、`plan_token`，以及 `resolutions.target_ids`、可选 `resolutions.names` 和 `resolutions.filesystem_bindings`。

配置库根据当前名称输入、服务端 blocker 和 Filesystem binding 实时决定是否允许导入；mapped directory 还需明确 path origin。名称冲突时服务端建议的新名称只作为提示，不会被当成用户已确认值；输入有效新名称后可提交，commit 仍由服务端按当前 active Repository 再次校验。commit 复用本次 preview 的 `bundle_sha256`、`plan_token` 和 target UUID map。导入成功后刷新当前列表并留在原页面。

导入不会按源 UUID 或名称复用、更新或覆盖配置。每条配置使用 preview 给出的新 UUID，声明式引用由后端机械重写；
名称冲突会建议 `Name (imported)`、`Name (imported 2)` 等后缀，冲突名称必须显式确认。Workflow 导入后固定为
`enabled=false`，需检查路径、credential、Skill、Python code 和依赖后再验证并启用。

单根 Bundle 的 manifest 固定保存 root `kind`、Component `type` 或 Workflow `role`，preview 会核对 root 与记录身份、依赖闭包、hash 和资源 owner。导入目标类型由已校验 manifest 决定，不由当前页面分类或文件名推断，因此 Filesystem Bundle 不会被写成 Filesystem Permissions。【配置库 / 全局 / 组件配置】的下载使用独立的 `agent-shell.configuration-repository` 整仓库格式；当前只提供整仓库下载，不提供整仓库上传恢复。

未知或不受信任的配置可能包含以 Agent Shell 权限运行的 Python/Skill 代码、文件系统访问、网络访问或欺骗性引用。导入或分享前必须检查来源、提示词、Skill 文件、Python 源码、requirements、文件系统绑定与权限。preview 的 warning 使用稳定 `message_key/message_args` 本地化显示，不直接把后端英文作为普通界面文案。

 Python-backed Component 会携带完整 owner package，并在目标实例用新 UUID 重建 folder 和 `package.json.id`；导入过程只做
 静态扫描，不 import factory。Skill Component 携带完整 owner private package，目标实例始终用新 Component UUID 重建目录，不做全局 Skill 名称复用或冲突判断。Filesystem 的绝对 mapped path、
 virtual directory `source_path` 和 virtual file `source_path` 都必须在目标实例显式重绑；data-root-relative mapped path 会保留，
它必须是没有 drive、root、冒号和 `.`/`..` 段的相对路径；合法目标不存在时 preview 给出 warning。损坏 ZIP、manifest、hash、entry path 或请求格式返回 422；digest、preview plan、名称或目标实例状态冲突返回 409。
