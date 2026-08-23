# 文件系统

文件系统组件配置请求级 workspace、宿主目录映射、初始虚拟文件和模型可见文件工具。

```json
{
  "name": "写作工作区",
  "mapped_directories": [
    {
      "virtual_path": "/output/",
      "local_path": "H:\\novel\\output",
      "path_origin": "absolute",
      "lifecycle_mode": "fixed"
    },
    {
      "virtual_path": "/scratch/",
      "local_path": "files\\scratch-roots",
      "path_origin": "data-root-relative",
      "lifecycle_mode": "dynamic"
    }
  ],
  "virtual_directories": [
    {"virtual_path": "/drafts/", "source_path": "H:\\novel\\drafts"}
  ],
  "virtual_files": [
    {"virtual_path": "/instructions/AGENT.md", "source_path": "H:\\novel\\AGENT.md"}
  ],
  "system_prompt_override": null,
  "tool_token_limit_before_evict": 20000,
  "human_message_token_limit_before_evict": 50000,
  "grep_max_count": 1000,
  "max_execute_timeout": 3600,
  "tool_configs": {
    "ls": {"visible": true, "description_override": null},
    "read_file": {"visible": true, "description_override": null},
    "write_file": {"visible": true, "description_override": null},
    "edit_file": {"visible": true, "description_override": null},
    "delete": {"visible": false, "description_override": null},
    "glob": {"visible": true, "description_override": null},
    "grep": {"visible": true, "description_override": null},
    "execute": {"visible": false, "description_override": null}
  }
}
```

## 两档运行模式

- 未选择项目 Filesystem：使用请求级默认 StateBackend 和“最小功能”，普通 workspace 初始为空；Deep Agents
  的 FilesystemMiddleware 要求 `read_file` 始终存在，因此模型只获得 `read_file`。选择 Skill 后，该工具也用于
  读取 Agent 独立的只读 `/skills/` 视图。
- 选择项目 Filesystem：使用配置的共享 workspace，并按 `tool_configs` 开放 `ls`、`read_file`、
  `write_file`、`edit_file`、`delete`、`glob`、`grep`。`read_file` 固定可见；`execute` 固定不可见；
  `delete` 默认关闭。`glob` 未以 `/` 开头的模式递归匹配整个虚拟文件树，例如 `*.py`；`/*.py` 才只匹配虚拟根目录。

同一个 Workflow Run 中的 Main Agent 与同步 Subagent 按 Deep Agents 官方行为共享普通 StateBackend 文件状态；每个 Agent 按自己的有效 Filesystem 构造初始文件和 mapped route 视图，Subagent 可继承、选择自己的项目 Filesystem 或回到最小 Filesystem。
独立后台 Run 各自拥有私有 StateBackend，不复制或合并其中的临时文件；同一 Lifecycle 的父 Run 和后台 Run 通过相同的 resolved mapped route 共享已落盘文件。每个 Agent 的 `/skills/` 仍按最终 Skill 选择建立只读视图。需要让不同 Agent 对共享 workspace 使用不同路径权限、文件工具或文件系统提示词时，另行选择[文件系统权限](filesystem-permissions-config.md)。

## 来源类型

- `mapped_directories`：把虚拟目录实时映射到宿主目录；写入直接落盘。`path_origin=absolute` 要求
  `local_path` 是宿主绝对路径；`path_origin=data-root-relative` 以当前实例 `data/` 为根解析相对路径；
  `lifecycle_mode=fixed` 直接使用配置目录，`lifecycle_mode=dynamic` 则在该目录下为每个顶层 Workflow
  Lifecycle 创建一次 `lifecycle-{uuid}` 子目录。同一 Lifecycle 的父 Run 和后台 Run 复用同一解析结果；
- `virtual_directories`：每次请求开始时把现有目录文件复制到内存 workspace，不回写来源；`source_path` 必须是宿主绝对路径，不支持 `data-root-relative`；
- `virtual_files`：每次请求复制一个现有普通文件，不回写来源；`source_path` 必须是宿主绝对路径，不支持 `data-root-relative`。

虚拟目录必须以 `/` 开头和结尾；虚拟文件以 `/` 开头且文件名与来源相同。不允许 `..`、重叠 route、
重复目标、文件/目录冲突、符号链接、junction 或其他 reparse point。以下 namespace 保留：
`/large_tool_results/`、`/conversation_history/`、`/skills/`、`/memory/`、`/memories/`。
Deep Agents 在 `/conversation_history/{session_uuid}.md` 保存摘要前的原始消息；session UUID 只用于隔离运行时内部摘要会话，
不对应产品的 Lifecycle、thread 或用户对话历史。

`system_prompt_override=null` 使用当前 Deep Agents 默认行为；工具 `description_override=null` 保留默认说明。
`tool_token_limit_before_evict` 为正整数或 `null`，`null` 关闭大工具结果卸载；
`human_message_token_limit_before_evict` 控制用户消息卸载阈值，`grep_max_count` 控制 grep 默认结果上限，
`max_execute_timeout` 是 execute 单次命令的最大秒数（execute 当前默认不可见，但仍可提前配置）。
没有装配文件系统权限时，路径默认可读写，文件系统组件中的提示词和工具配置直接生效。

动态目录不会在 Workflow End 时隐式删除，生命周期清理由管理能力显式处理。磁盘目录不进入 checkpoint，平台也不处理多个 Agent 同时写同一文件的冲突。虚拟来源会在每个新请求中重新完整读取，当前没有单文件、展开文件数或总字节配额。不要选择依赖缓存、
构建产物、媒体目录或其他大型路径。并行 Subagent 不应同时修改同一临时文件。
