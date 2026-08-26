# Filesystem Backend

【文件系统后端】是 Main Agent 和 Subagent 的必选 capability。每份配置在 `CompositeBackend` 与 `LocalShellBackend` 中二选一；后端只定义文件来源、路径权限、可选 Skill 独立包和文件系统提示词，模型可见工具由独立的[文件系统工具](filesystem-tools-config.md)配置。

## CompositeBackend

CompositeBackend 组合请求级 `StateBackend`、真实目录映射、请求开始时复制的虚拟来源，以及可选的 Skill 独立包：

```json
{
  "name": "写作工作区",
  "backend_type": "composite",
  "mapped_directories": [
    {
      "virtual_path": "/output/",
      "local_path": "H:\\novel\\output",
      "path_origin": "absolute",
      "lifecycle_mode": "fixed",
      "permission": "read-write"
    },
    {
      "virtual_path": "/scratch/",
      "local_path": "files\\scratch-roots",
      "path_origin": "data-root-relative",
      "lifecycle_mode": "dynamic",
      "permission": "read-only"
    }
  ],
  "virtual_directories": [
    {
      "virtual_path": "/drafts/",
      "source_path": "H:\\novel\\drafts",
      "permission": "read-write"
    }
  ],
  "virtual_files": [
    {
      "virtual_path": "/instructions/AGENT.md",
      "source_path": "H:\\novel\\AGENT.md",
      "permission": "no-access"
    }
  ],
  "skill_package_id": "<skill-component-uuid-or-null>",
  "system_prompt_override": null
}
```

每条来源自己的 `permission` 可选 `read-write`、`read-only`、`no-access`，默认 `read-write`。来源发生父子嵌套时，更具体的虚拟路径权限优先生效。权限只约束 Deep Agents FilesystemMiddleware 提供的文件操作；Custom Tool、Custom Middleware、外部程序和管理台文件管理使用各自的权限边界。

来源类型：

- `mapped_directories` 把虚拟目录实时映射到宿主目录，允许的写入直接落盘。`path_origin=absolute` 要求宿主绝对路径；`path_origin=data-root-relative` 以实例 `data/` 为根解析。`lifecycle_mode=fixed` 直接使用配置目录；`lifecycle_mode=dynamic` 在配置目录下为每个 top-level Workflow Lifecycle 创建一次 `lifecycle-{uuid}` 子目录，同一 Lifecycle 的 parent Run 和 background Run 复用该路径；
- `virtual_directories` 在每次请求开始时把现有目录复制到请求级 StateBackend，来源目录保持原样；
- `virtual_files` 在每次请求开始时把现有普通文件复制到请求级 StateBackend，来源文件保持原样。

`skill_package_id` 可选择一份由 Skill Component 制作的 Skill 独立包。运行时把该包只读挂载到 `/skills/`，并装配官方 SkillsMiddleware。Skill 包引用属于 Filesystem Backend，因此 Subagent 继承该 Backend 时同时继承包、路径和权限；替换 Backend 时使用新 Backend 的完整配置。Agent 不直接选择 Skill Component。

CompositeBackend 不提供 `execute`。即使关联的文件系统工具配置把 `execute.visible` 设为 `true`，Deep Agents 也会根据 Backend 能力从模型可见工具中移除它。

## LocalShellBackend

LocalShellBackend 把一个已经存在的真实目录作为虚拟根 `/`：

```json
{
  "name": "本地开发工作区",
  "backend_type": "local-shell",
  "workspace": {
    "local_path": "H:\\projects\\my-app",
    "path_origin": "absolute"
  },
  "system_prompt_override": null
}
```

`workspace` 只包含 `local_path` 与 `path_origin=absolute|data-root-relative`。它是固定工作区，不提供 lifecycle dynamic 模式；运行时直接构造 `LocalShellBackend(root_dir=workspace, virtual_mode=True)`，不创建空执行目录，也没有对应的目录清理程序。Deep Agents 不需要为这个直接 Backend 追加虚拟路径到宿主路径的 mapping 提示。

LocalShellBackend 不接受 Composite 来源或 `skill_package_id`，也没有来源级权限。需要 Skill、混合映射或路径权限时使用 CompositeBackend；需要在真实单工作区中执行命令时使用 LocalShellBackend，并在文件系统工具中显式开启 `execute`。`execute` 直接以 Agent Shell 服务账号权限在宿主机运行命令，没有 sandbox；workspace 只是默认工作目录，命令仍可访问该账号有权访问的其他文件、进程、网络和系统资源。

## 路径与运行边界

虚拟目录必须以 `/` 开头和结尾；虚拟文件以 `/` 开头且文件名与来源相同。不允许 `..`、重叠 route、重复目标、文件/目录冲突、符号链接、junction 或其他 reparse point。以下 namespace 保留：`/large_tool_results/`、`/conversation_history/`、`/skills/`、`/memory/`、`/memories/`。

Deep Agents 在 selected Backend 的 `/conversation_history/` 与 `/large_tool_results/` 保存内部 artifact。CompositeBackend 的 default 是请求级 StateBackend；LocalShellBackend 直接使用真实 workspace，因此会在 workspace 创建这些目录和文件。LocalShell 不叠加 StateBackend route，因为 Deep Agents 0.7.7 会为 Composite + execute 无条件追加虚拟路径与宿主路径说明，Filesystem 自定义提示词不能关闭该追加。conversation history UUID 只隔离运行时内部摘要会话，不对应产品 Lifecycle、thread 或用户对话历史。

同一个 Workflow Run 中的 Main Agent 与 synchronous Subagent 共享 Deep Agents StateBackend 文件状态，但各自使用自己继承或替换后的 Filesystem Backend 和 Filesystem Tools。独立 background Run 不复制或合并请求级文件；CompositeBackend 的真实 mapped route 可以让引用同一配置的 Run 访问同一落盘目录。

动态目录不会在 Workflow End 时隐式删除，只能由 Lifecycle 管理显式清理。LocalShell workspace 与 fixed mapped directory 都不属于受管动态目录，Lifecycle 清理不会删除它们。磁盘目录不进入 checkpoint，平台也不处理多个 Agent 同时写同一文件的冲突。
